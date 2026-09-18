#!/usr/bin/env python3
"""Tenshi ⇄ GitHub 的推送落库统一入口（替代各 workflow 里逐份拷贝的 push 重试模板）。

为什么存在
──────────
2026-09-18 排查发现：Calling 的 `telegram_webhook` 会**间歇性**在
`Commit and Push Changes (to Tenshi repo)` 步骤以 exit 1 失败，而日志里
只有一句 `Process completed with exit code 1.`。原因是：

1. 至少 6 个 workflow 都在往 Tenshi `main` 推送（回复、感知、总结、探活、
   日志归档、周度归档、月度保活、手动 DB…），没有任何互斥；
2. 撞车后那段「push → fetch → rebase → 冲突时 checkout --ours → 重试」
   的模板有两个致命毛病：
   · 冲突解决把文件整体换成**上游版本**（rebase 中 `--ours` 是上游），
     于是本次运行的改动被静默丢弃，rebase 还会卡在 `.git/rebase-merge`
     里，之后每一轮 push 都以 128 失败；
   · 全程 `>/dev/null 2>&1`，失败原因一个字节都不留。
3. `git add secure_failures/...` 没带 `--sparse`，被 sparse-checkout 拒绝后
   又用 `|| true` 吞掉，导致「加密失败包已推送」是假的（`secure_failures/`
   里最后一个包停在 2026-05-19）。

本脚本用一份实现替掉那套模板，并给出三档策略：

  reply    —— 用户回复链路。最高优先级：**无论如何都要落到 main**。
  summary  —— 长期记忆总结。要求同样落 main（下次总结要能读到游标），
              但可以接受较长退避。
  perceive —— 感知层。落在 main，但可接受较长退避。
  edge     —— 归档/保活/清理等边缘流程。**推独立分支**，永不与 main 抢；
              由 `merge_staging` 统一汇流。

冲突处理是**无损**的：不再整体取舍，而是做行级三方合并（拒绝合并或长度
不可信时退回「尽量保住双方」），实在算不出来时优先保住本分支内容并把
两侧的原始版本打印出来，绝不再静默丢数据。

用法
────
    python scripts/tenshi_git_sync.py push --tier reply \
        --message "天子已阅：对话与痕迹入档 [skip ci]" \
        --files Tenshi.json data/tenshi_log.json logs/debug.log

    python scripts/tenshi_git_sync.py merge-staging     # 汇流边缘分支

退出码：0 成功（包含「本来就没有改动」）；非 0 表示确实没能落库。
"""

from __future__ import annotations

import argparse
import difflib
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_BRANCH = "main"
STAGING_PREFIX = "bot-staging"

# git 在 rebase --continue / merge 收尾时会尝试打开编辑器改写提交信息。
# 在 CI（以及任何非交互环境）里必须钉死成非交互，否则会以
# "there was a problem with the editor" 失败并把 rebase 留在半途。
os.environ.setdefault("GIT_EDITOR", "true")
os.environ.setdefault("GIT_SEQUENCE_EDITOR", "true")
os.environ.setdefault("GIT_TERMINAL_PROMPT", "0")

# 单文件超过这个大小且无法做行级合并时，不再尝试三方合并（直接保留本分支）。
MAX_REAL_MERGE_BYTES = 64 * 1024 * 1024

# 运行期产生的中间文件：永远不入库（避免把临时垃圾带进 commit）。
RUNTIME_SKIP_SUFFIXES = (".orig", ".rej", ".lock")

# 二进制/数据库类文件没法做行级合并。
BINARY_SUFFIXES = (
    ".db",
    ".sqlite",
    ".sqlite3",
    ".pkl",
    ".gz",
    ".zip",
    ".tar",
    ".tgz",
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".gif",
    ".mp4",
    ".pdf",
)

# 每档的重试预算：(尝试次数, 首次退避秒数, 退避上限秒数)
TIER_BUDGET = {
    "reply": (7, 2.0, 20.0),
    "summary": (6, 3.0, 30.0),
    "perceive": (5, 3.0, 30.0),
    "edge": (3, 2.0, 10.0),
}

# 推 main 的档位（其余走独立分支）。
DIRECT_TIERS = ("reply", "summary", "perceive")

# git 提交身份。这不是随便填的：本仓库把 git 历史当作角色的痕迹，
# persona.py 里 ROLE_GIT_NAME/ROLE_GIT_EMAIL 就是「天子」这个身份的登记处
# （persona.py 的注释特别点名了 workflow 的 git 身份）。
#
# 注意：runner 容器里 HOME=/github/home，没有全局 gitconfig；checkout 步骤
# 注入的 GIT_AUTHOR_* 也只保证有值、不保证是角色名。**不显式设置身份时
# git commit 会直接以 128 失败**（"Author identity unknown"），所以这套身份
# 必须由本脚本负责下发，而不是靠「反正环境里有」。
DEFAULT_GIT_NAME = "比那名居 天子"
DEFAULT_GIT_EMAIL = "268836736+ZenjinruiNoHisouten@users.noreply.github.com"


class SyncError(RuntimeError):
    """任意一步 git 操作失败。"""


@dataclass
class Repo:
    """一次 git 调用的薄封装。"""

    path: Path
    committed_sha: str = ""
    pushed_sha: str = ""

    def head(self) -> str:
        return self.out("rev-parse", "HEAD")

    def refresh_head(self) -> str:
        """把 pushed_sha 对齐到「现在真正要推的那个提交」。

        rebase 会**重写**提交，SHA 随之变化，所以不能沿用 commit 当时的那个值 ——
        否则 push 之后核对必然失败（这是 2026-09-18 加核对时踩到的坑）。
        """
        self.pushed_sha = self.head()
        return self.pushed_sha

    def git(
        self,
        *args: str,
        check: bool = True,
        capture: bool = True,
        timeout: int | None = None,
    ) -> subprocess.CompletedProcess:
        cmd = ["git", *args]
        proc = subprocess.run(
            cmd,
            cwd=str(self.path),
            capture_output=capture,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        if check and proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip()
            raise SyncError(
                f"`git {' '.join(args)}` 失败（exit {proc.returncode}）"
                + (f"：{detail}" if detail else "")
            )
        return proc

    def out(self, *args: str) -> str:
        return (self.git(*args).stdout or "").strip()

    def resolve(self, rev: str) -> str:
        return self.out("rev-parse", rev)


def log(message: str) -> None:
    print(f"[tenshi-sync] {message}", flush=True)


def warn(message: str) -> None:
    print(f"[tenshi-sync] ::warning::{message}", flush=True)


def err(message: str) -> None:
    print(f"[tenshi-sync] ::error::{message}", file=sys.stderr, flush=True)


# ────────────────────────────── 冲突合并 ──────────────────────────────


def _is_binary_path(path: str) -> bool:
    if path.startswith("downloads/"):
        return True
    return path.lower().endswith(BINARY_SUFFIXES)


def _read_text(path: Path) -> str | None:
    try:
        if path.stat().st_size > MAX_REAL_MERGE_BYTES:
            return None
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _lines(text: str) -> list[str]:
    return text.splitlines()


def _looks_append_only(ours: list[str], theirs: list[str]) -> bool:
    """粗略判断「一边是否为另一边的追加」。"""
    if not ours or not theirs or len(ours) > len(theirs):
        return False
    return theirs[: len(ours)] == ours


def _merge_append_only(ours: list[str], theirs: list[str]) -> list[str] | None:
    """两边互为追加（典型：同一条日志被两个 run 各追加一段）→ 直接拼接。"""
    if not ours:
        return list(theirs)
    if not theirs:
        return list(ours)
    if _looks_append_only(ours, theirs):
        return list(theirs)
    if _looks_append_only(theirs, ours):
        return list(ours)
    return None


def _rebuild(markup: list[str], side: str) -> list[str]:
    """把 merge-file 的冲突标记按一侧拍平（用于安全网比对）。"""
    out: list[str] = []
    state = "common"
    for line in markup:
        if line.startswith("<<<<<<<"):
            state = "mine" if side == "mine" else "common"
            continue
        if line.startswith("|||||||"):
            if side == "both":
                state = "mine"
            continue
        if line.startswith("======="):
            state = "base" if side == "base" else ("theirs" if side == "theirs" else "common")
            if side == "both":
                state = "theirs"
            continue
        if line.startswith(">>>>>>>"):
            state = "common"
            continue
        if state in ("common", side):
            out.append(line)
    return out


def _flatten_conflicts(markup: list[str]) -> list[str]:
    """逐行处理冲突块：本侧内容保留，对侧多出来的行补在后面。"""
    out: list[str] = []
    ours_block: list[str] = []
    theirs_block: list[str] = []
    state = "common"
    for line in markup:
        if line.startswith("<<<<<<<"):
            state = "ours"
            ours_block, theirs_block = [], []
            continue
        if line.startswith("|||||||"):
            state = "base"
            continue
        if line.startswith("=======") and state in ("ours", "base"):
            state = "theirs"
            continue
        if line.startswith(">>>>>>>"):
            merged = _merge_append_only(ours_block, theirs_block)
            if merged is None:
                merged = list(ours_block)
                extra = [ln for ln in theirs_block if ln and ln not in set(ours_block)]
                if extra:
                    merged = merged + extra
            out.extend(merged)
            state = "common"
            continue
        if state == "common":
            out.append(line)
        elif state in ("ours", "base"):
            ours_block.append(line)
        elif state == "theirs":
            theirs_block.append(line)
    return out


def _all_survive(merged: list[str], ours: list[str], theirs: list[str]) -> bool:
    """安全网：两侧的非空行必须都在结果里，否则宁可放弃这次自动合并。"""
    have = set(merged)
    return all(ln in have for ln in ours if ln) and all(ln in have for ln in theirs if ln)


def _is_json_like(text: str) -> bool:
    head = text.lstrip()[:1]
    return head in ("{", "[")


def _json_id(item: Any) -> str | None:
    if not isinstance(item, dict):
        return None
    for key in ("msg_id", "id", "uuid", "key", "name"):
        if key in item and isinstance(item[key], (str, int)):
            return f"{key}={item[key]}"
    return None


def _json_merge(ours: Any, theirs: Any) -> Any:
    """结构化合并：dict 逐键合并、list 按 id 对齐后补上对侧独有项。"""
    if isinstance(ours, dict) and isinstance(theirs, dict):
        out = dict(theirs)
        for key, value in ours.items():
            out[key] = _json_merge(value, out[key]) if key in out else value
        return out
    if isinstance(ours, list) and isinstance(theirs, list):
        if len(ours) >= len(theirs) and ours[: len(theirs)] == theirs:
            return list(ours)
        if len(theirs) > len(ours) and theirs[: len(ours)] == ours:
            return list(theirs)
        out = list(theirs)
        seen = {_json_id(item) for item in out if _json_id(item)}
        for item in ours:
            item_id = _json_id(item)
            if item_id is None or item_id not in seen:
                out.append(item)
        return out
    # 标量冲突：保留本分支的值。
    return ours


def _json_survive(merged: Any, ours: Any, theirs: Any) -> bool:
    """保守校验：不要求完全相等（标量会取一侧），但两侧的键与独有条目必须还在。"""
    if isinstance(merged, dict) and isinstance(ours, dict) and isinstance(theirs, dict):
        return set(ours) <= set(merged) and set(theirs) <= set(merged) and all(
            _json_survive(merged[k], ours[k], theirs[k]) for k in set(ours) & set(theirs)
        )
    if isinstance(merged, list) and isinstance(ours, list) and isinstance(theirs, list):
        have = {_json_id(i) for i in merged if _json_id(i)}
        for side in (ours, theirs):
            for item in side:
                item_id = _json_id(item)
                if item_id is not None and item_id not in have:
                    return False
        return True
    return True


def _json_text_merge(ours_text: str, theirs_text: str, label: str) -> list[str] | None:
    """两边都是 JSON 时优先按结构合并，避免把数组追加拼成非法 JSON。"""
    import json

    try:
        ours_obj = json.loads(ours_text)
        theirs_obj = json.loads(theirs_text)
    except Exception:
        return None
    merged = _json_merge(ours_obj, theirs_obj)
    if not _json_survive(merged, ours_obj, theirs_obj):
        warn(f"{label}：结构化合并会丢掉某一侧的条目，改用行级合并")
        return None
    text = json.dumps(merged, ensure_ascii=False, indent=2) + "\n"
    if not _is_json_valid(text):
        return None
    log(f"{label}：已按 JSON 结构无损合并")
    return _lines(text)


def _is_json_valid(text: str) -> bool:
    import json

    try:
        json.loads(text)
        return True
    except Exception:
        return False


def _line_merge(ours_text: str, base_text: str, theirs_text: str, label: str) -> list[str] | None:
    """三方合并；失败返回 None（调用方退回保守策略）。"""
    if _is_json_like(ours_text) and _is_json_like(theirs_text):
        structured = _json_text_merge(ours_text, theirs_text, label)
        if structured is not None:
            return structured

    ours, base, theirs = _lines(ours_text), _lines(base_text), _lines(theirs_text)

    quick = _merge_append_only(ours, theirs)
    if quick is not None:
        return quick

    tmpdir = Path(tempfile.mkdtemp(prefix="tenshi-sync-"))
    try:
        p_ours, p_base, p_theirs = (tmpdir / n for n in ("ours", "base", "theirs"))
        for target, lines in ((p_ours, ours), (p_base, base), (p_theirs, theirs)):
            target.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        proc = subprocess.run(
            [
                "git",
                "merge-file",
                "-p",
                "--diff3",
                "-L",
                "本分支",
                "-L",
                "共同祖先",
                "-L",
                "远端",
                str(p_ours),
                str(p_base),
                str(p_theirs),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        returncode, stdout = proc.returncode, proc.stdout
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    # 0 = 干净合并；1 = 有冲突（标记已在输出里）；>=2 = 真出错。
    if returncode >= 2:
        warn(f"{label}：git merge-file 返回 {returncode}，放弃行级合并")
        return None
    markup = _lines(stdout or "")

    if returncode == 0:
        merged = markup
    else:
        merged = _flatten_conflicts(markup)

    if not _all_survive(merged, ours, theirs):
        warn(f"{label}：行级合并会丢掉某一侧的内容，放弃自动合并")
        return None

    # 结构化 JSON 走行级拼合有概率拼出非法 JSON（数组里两个元素在同一行冲突）。
    # 宁可退回「只保留本分支」，也不能把坏掉的 JSON 写进仓库。
    if _is_json_like(ours_text) and _is_json_like(theirs_text) and not _is_json_valid("\n".join(merged)):
        warn(f"{label}：行级合并结果不是合法 JSON，放弃自动合并")
        return None
    return merged


def _write_merged(repo: Repo, path: str, merged: list[str], stages: dict[int, str]) -> None:
    target = repo.path / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(merged) + ("\n" if merged else ""), encoding="utf-8")
    repo.git("add", "--sparse", "--", path)
    log(f"已做无损合并：{path}（base={stages[1][:8]} ours={stages[2][:8]} theirs={stages[3][:8]}）")


def _keep_branch_version(repo: Repo, path: str) -> None:
    """保守兜底：保留本分支（rebase 中的 stage#3）版本，并保证文件在索引里。"""
    target = repo.path / path
    if target.exists():
        repo.git("add", "--sparse", "--", path)
        warn(f"无法自动合并，保留本分支内容：{path}")
    else:
        # 本分支没有这个文件（对侧新增）→ 采用对侧版本，不要把它删掉。
        repo.git("checkout", "--theirs", "--", path, check=False)
        repo.git("add", "--sparse", "--", path, check=False)
        warn(f"无法自动合并，采用远端新增内容：{path}")


def _parse_unmerged(repo: Repo) -> dict[str, dict[int, str]]:
    """git ls-files -u → {path: {stage: blob}}。"""
    result: dict[str, dict[int, str]] = {}
    for line in (repo.git("ls-files", "-u").stdout or "").splitlines():
        parts = line.split("\t")
        if len(parts) != 2:
            continue
        meta = parts[0].split()
        if len(meta) < 3:
            continue
        mode, blob, stage = meta[0], meta[1], meta[2]
        _ = mode
        result.setdefault(parts[1], {})[int(stage)] = blob
    return result


def _resolve_conflicts(repo: Repo, resolved: set[str]) -> bool:
    """解决当前冲突集；返回 True 表示「所有冲突都已处理，可以继续 rebase」。"""
    conflicts = _parse_unmerged(repo)
    if not conflicts:
        return False
    seen_before = False
    for path, stages in conflicts.items():
        if path in resolved:
            # 同一个文件在 rebase 推进后又冲突：说明冲突链比预期深，
            # 继续自动合并不安全，交给上层 abort 后重来。
            seen_before = True
            warn(f"冲突在本轮重复出现，停止自动处理：{path}")
            continue
        if _is_binary_path(path):
            _keep_branch_version(repo, path)
            resolved.add(path)
            continue
        if 1 not in stages or 2 not in stages or 3 not in stages:
            _keep_branch_version(repo, path)
            resolved.add(path)
            continue
        ours_text = repo.git("show", stages[2]).stdout or ""
        base_text = repo.git("show", stages[1]).stdout or ""
        theirs_text = repo.git("show", stages[3]).stdout or ""
        if _is_binary_path(path) or "\x00" in ours_text[:8192] or "\x00" in theirs_text[:8192]:
            _keep_branch_version(repo, path)
            resolved.add(path)
            continue
        merged = _line_merge(ours_text, base_text, theirs_text, path)
        if merged is None:
            _keep_branch_version(repo, path)
        else:
            _write_merged(repo, path, merged, stages)
        resolved.add(path)
    return not seen_before


def _rebase_in_progress(repo: Repo) -> bool:
    """git 自己用这两个目录判断「正在 rebase」。"""
    git_dir = repo.path / ".git"
    return (git_dir / "rebase-merge").exists() or (git_dir / "rebase-apply").exists()


def _abort_rebase(repo: Repo) -> None:
    repo.git("rebase", "--abort", check=False)
    shutil.rmtree(repo.path / ".git" / "rebase-merge", ignore_errors=True)
    shutil.rmtree(repo.path / ".git" / "rebase-apply", ignore_errors=True)


def sync_to_remote(repo: Repo, branch: str) -> str:
    """把本分支同步到 origin/<branch>。

    返回："done"（已就位）/ "elsewhere"（rebase 之后落在别的提交上，应当重试 push）。
    """
    repo.git("fetch", "origin", branch)
    remote_rev = repo.git("rev-parse", f"refs/remotes/origin/{branch}").stdout.strip()
    head_rev = repo.out("rev-parse", "HEAD")
    if head_rev == remote_rev:
        log(f"本地已与 origin/{branch}（{remote_rev[:8]}）一致")
        return "done"
    if repo.git("merge-base", "--is-ancestor", remote_rev, "HEAD", check=False).returncode == 0:
        log(f"本地领先 origin/{branch}（{remote_rev[:8]}），直接推送")
        return "done"

    log(f"远端已前进到 {remote_rev[:8]}，rebase 到 origin/{branch}")
    # 刻意不加 `-X theirs`：那会让 git 在冲突处整块取本分支版本，
    # 把远端在这段时间里的写入悄悄丢掉。改为先让 git 报冲突，再逐文件做
    # 行级三方合并，尽量保住双方。
    rebase = repo.git("rebase", "--autostash", f"origin/{branch}", check=False)
    if rebase.returncode == 0:
        return "done"

    resolved: set[str] = set()
    for round_no in range(1, 41):
        if not _rebase_in_progress(repo):
            break
        if not _resolve_conflicts(repo, resolved):
            break
        cont = repo.git("rebase", "--continue", check=False)
        if cont.returncode == 0:
            return "done"
        if not _parse_unmerged(repo):
            # 没有冲突却仍然失败：多半是 autostash 回放失败之类的结构性错误。
            warn("rebase 无冲突但无法继续，放弃本次 rebase")
            break
        log(f"仍有冲突，继续处理（第 {round_no} 轮）")

    if not _rebase_in_progress(repo) and _parse_unmerged(repo) == {}:
        # rebase 已经自然走完（部分 git 版本 --continue 会返回非零但确实完成）。
        log("rebase 已完成")
        return "done"

    warn("rebase 未能自动完成，已放弃并回到推之前的状态（本次改动仍在本地提交里）")
    _abort_rebase(repo)
    return "elsewhere"


def build_staging_branch(run_id: str, workflow: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in workflow).strip("-") or "tenshi"
    return f"{STAGING_PREFIX}/{safe}-{run_id}"


def commit_unit(
    repo: Repo,
    files: list[str],
    message: str,
    *,
    skip_extras: bool = True,
) -> bool:
    """按 whitelist 暂存并提交。返回 True 表示产生了新提交。"""
    staged: list[str] = []
    for path in files:
        if not (repo.path / path).exists():
            continue
        if skip_extras and path.endswith(RUNTIME_SKIP_SUFFIXES):
            continue
        staged.append(path)
    if not staged:
        warn("指定的文件都不存在，没有可提交的内容")
        return False
    # `--sparse` 是关键：白名单外的路径也必须能进来，否则会以
    # "outside of your sparse-checkout definition" 静默拒绝。
    repo.git("add", "--sparse", "--", *staged)
    diff = repo.git("diff", "--cached", "--quiet", check=False)
    if diff.returncode == 0:
        log("工作区没有产生新变更（可能本次运行没写数据），无需提交")
        return False
    branch = repo.git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip() or "HEAD"
    repo.git("commit", "-m", message)
    repo.committed_sha = repo.out("rev-parse", "HEAD")
    log(f"已提交到 {branch}：{repo.committed_sha[:8]}")
    return True


def write_github_output(**values: str) -> None:
    """把结果写给 workflow 的 $GITHUB_OUTPUT（没有该变量时静默跳过）。"""
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    try:
        with open(path, "a", encoding="utf-8") as handle:
            for key, value in values.items():
                if value:
                    handle.write(f"{key}={value}\n")
    except OSError as exc:
        warn(f"写 GITHUB_OUTPUT 失败：{exc}")


def verify_landed(repo: Repo, branch: str, sha: str) -> bool:
    """push 之后本地核对：远端分支是否真的已经包含这次提交。

    这是「落库保证」的真正落点 —— 只依赖 git 自己（push 之后的一次浅 fetch），
    不依赖 gh、不依赖令牌额外权限、也不怕 GitHub API 抖动。
    """
    if not sha:
        return True
    try:
        repo.git("fetch", "origin", branch)
        remote_rev = repo.out("rev-parse", f"refs/remotes/origin/{branch}")
    except SyncError as exc:
        warn(f"落库核对无法完成（fetch 失败），以 push 返回值作为结论：{exc}")
        return True
    if remote_rev == sha:
        log(f"落库核对通过：{branch} 就在本次提交 {sha[:8]}")
        return True
    if repo.git("merge-base", "--is-ancestor", sha, remote_rev, check=False).returncode == 0:
        log(f"落库核对通过：{sha[:8]} 已在 {branch}（{remote_rev[:8]}）的历史里")
        return True
    # 一般是被别人抢先推进了，这一轮不算成功；交给上层重试。
    warn(f"落库核对未通过：{sha[:8]} 不在 {branch}（{remote_rev[:8]}）的历史里")
    return False


def push_direct(
    repo: Repo,
    branch: str,
    *,
    tier: str,
    attempts: int | None = None,
    base_delay: float | None = None,
    max_delay: float | None = None,
) -> bool:
    """带正确同步与退避的重试推送。被抢推时重试，绝不静默失败。"""
    default_attempts, default_base, default_max = TIER_BUDGET.get(tier, TIER_BUDGET["edge"])
    attempts = attempts or default_attempts
    base_delay = base_delay if base_delay is not None else default_base
    max_delay = max_delay if max_delay is not None else default_max

    last_error = ""
    for attempt in range(1, attempts + 1):
        # 每轮都重新对齐：上一轮的 rebase 可能重写过提交
        repo.refresh_head()
        push = repo.git("push", "origin", f"HEAD:refs/heads/{branch}", check=False)
        if push.returncode == 0:
            log(f"已推送到 {branch}（第 {attempt}/{attempts} 次尝试）")
            if verify_landed(repo, branch, repo.pushed_sha):
                return True
            last_error = "push 返回成功，但远端历史里没有这次提交"
        else:
            last_error = (push.stderr or push.stdout or "").strip()
            log(f"推送被拒（第 {attempt}/{attempts} 次）：{last_error.splitlines()[-1] if last_error else '未知原因'}")

        if attempt == attempts:
            break
        _abort_rebase(repo)
        try:
            sync_to_remote(repo, branch)
        except SyncError as exc:
            warn(f"同步远端失败：{exc}")
        delay = min(max_delay, base_delay * (2 ** (attempt - 1))) + random.uniform(0, 1.0)
        log(f"{delay:.1f}s 后重试")
        time.sleep(delay)

    err(f"连续 {attempts} 次都没能把改动推到 {branch}。最后一次错误：{last_error or '（git 没有输出）'}")
    return False


def push_branch(
    repo: Repo,
    branch: str,
    run_id: str,
    workflow: str,
    *,
    attempts: int = 3,
    base_delay: float = 2.0,
) -> bool:
    """边缘工具路径：把提交推到一个没人会碰的独立分支（永不与 main 抢）。"""
    target = build_staging_branch(run_id, workflow)
    last_error = ""
    for attempt in range(1, attempts + 1):
        push = repo.git("push", "origin", f"HEAD:refs/heads/{target}", check=False)
        if push.returncode == 0:
            log(f"已推送到独立分支 {target}（等 merge-staging 汇流到 {DEFAULT_BRANCH}）")
            # 同样做一次本地核对：这个分支只有我们推，核对不过多半是网络/权限问题
            try:
                head = repo.out("rev-parse", "HEAD")
                remote = repo.git("ls-remote", "--heads", "origin", target, check=False)
                remote_sha = (remote.stdout or "").split()[0] if (remote.stdout or "").strip() else ""
            except (SyncError, IndexError):
                remote_sha, head = "", ""
            if head and remote_sha and head != remote_sha:
                last_error = f"分支 {target} 推送后核对不一致：local={head[:8]} remote={remote_sha[:8]}"
                warn(last_error)
            else:
                return True
        else:
            last_error = (push.stderr or push.stdout or "").strip()
        delay = base_delay * attempt
        log(f"分支推送失败（第 {attempt}/{attempts} 次），{delay:.0f}s 后重试")
        time.sleep(delay)
    err(f"独立分支 {target} 推送失败：{last_error or '（git 没有输出）'}")
    return False


# ─────────────────────────── 边缘分支汇流 ───────────────────────────


def list_staging_branches(repo: Repo) -> list[str]:
    proc = repo.git("ls-remote", "--heads", "origin", f"{STAGING_PREFIX}/*", check=False)
    if proc.returncode != 0:
        raise SyncError(f"列远端分支失败：{(proc.stderr or '').strip()}")
    branches = []
    for line in (proc.stdout or "").splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].startswith("refs/heads/"):
            branches.append(parts[1][len("refs/heads/") :])
    return sorted(branches)


def _merge_staging_branch(repo: Repo, branch: str, branch_sha: str) -> bool:
    """把某个 staging 分支并回 main；冲突用同一套无损合并解决。"""
    repo.git("fetch", "origin", branch)
    merge = repo.git(
        "merge",
        "--no-ff",
        "--no-edit",
        "-m",
        f"汇流：{branch} [skip ci]",
        branch_sha,
        check=False,
    )
    if merge.returncode != 0:
        resolved: set[str] = set()
        for _ in range(1, 41):
            if not _parse_unmerged(repo):
                break
            if not _resolve_conflicts(repo, resolved):
                break
            cont = repo.git("commit", "--no-edit", check=False)
            if cont.returncode == 0:
                break
        if _parse_unmerged(repo):
            warn(f"{branch} 仍有未解决冲突，保留分支不动，等人工处理")
            repo.git("merge", "--abort", check=False)
            return False
    if repo.git("rev-parse", "--verify", "MERGE_HEAD", check=False).returncode == 0:
        repo.git("commit", "--no-edit", check=False)
    push = repo.git("push", "origin", f"HEAD:refs/heads/{DEFAULT_BRANCH}", check=False)
    if push.returncode != 0:
        warn(f"main 推送失败（可能又被别人抢了）：{(push.stderr or '').strip().splitlines()[-1:]}")
        repo.git("reset", "--hard", f"origin/{DEFAULT_BRANCH}", check=False)
        return False
    repo.git("push", "origin", "--delete", branch, check=False)
    log(f"已汇流 {branch} 到 {DEFAULT_BRANCH} 并删除该分支")
    return True


def merge_staging(repo: Repo) -> int:
    """把所有 bot-staging/* 分支汇流进 main。"""
    repo.git("fetch", "origin", DEFAULT_BRANCH)
    repo.git("checkout", "-B", DEFAULT_BRANCH, f"origin/{DEFAULT_BRANCH}")
    branches = list_staging_branches(repo)
    if not branches:
        log("没有待汇流的 bot-staging 分支")
        return 0

    failed: list[str] = []
    merged = 0
    for branch in branches:
        sha = repo.out("rev-parse", f"refs/remotes/origin/{branch}")
        # 每次都从最新 main 出发，避免分支之间互相污染。
        repo.git("checkout", "-B", DEFAULT_BRANCH, f"origin/{DEFAULT_BRANCH}")
        repo.git("reset", "--hard", f"origin/{DEFAULT_BRANCH}")
        log(f"汇流 {branch}（{sha[:8]}）")
        if _merge_staging_branch(repo, branch, sha):
            merged += 1
            repo.git("fetch", "origin", DEFAULT_BRANCH)
        else:
            failed.append(branch)
    if failed:
        warn(f"{len(failed)} 个分支未能汇流（保留在远端）：{', '.join(failed)}")
    log(f"汇流完成：成功 {merged} 个，失败 {len(failed)} 个")
    return 0


# ──────────────────────────────── CLI ────────────────────────────────


def _git_identity(args: argparse.Namespace) -> tuple[str, str]:
    """解析 git 提交身份。

    优先级：命令行 > 环境变量 > 角色默认值。
    必须在任何 commit 之前写进仓库 config —— runner 容器里没有全局身份，
    缺了它 git commit 会以 128 失败（"Author identity unknown"）。
    """
    name = (getattr(args, "git_name", "") or os.environ.get("TENSHI_GIT_NAME", "") or DEFAULT_GIT_NAME).strip()
    email = (
        getattr(args, "git_email", "") or os.environ.get("TENSHI_GIT_EMAIL", "") or DEFAULT_GIT_EMAIL
    ).strip()
    if not name or not email:
        raise SyncError(
            "git 提交身份为空：请用 --git-name/--git-email 或 TENSHI_GIT_NAME/TENSHI_GIT_EMAIL 指定"
        )
    return name, email


def _setup_repo(path: Path, *, identity: tuple[str, str] | None = None) -> Repo:
    repo = Repo(path=path)
    if not (path / ".git").exists():
        raise SyncError(f"{path} 不是 git 仓库（checkout 没生效？）")
    repo.git("config", "--global", "--add", "safe.directory", "*", check=False)
    # 显式补上 refspec：只写 `fetch origin main` 在部分环境下不会更新
    # refs/remotes/origin/main，会让 rebase 白做。
    repo.git("config", "remote.origin.fetch", f"+refs/heads/*:refs/remotes/origin/*", check=False)
    if identity is not None:
        name, email = identity
        # 写仓库级 config（不是 --global）：容器里 HOME 可能只读，而且这样
        # 只影响本次检出的这个仓库。
        repo.git("config", "user.name", name)
        repo.git("config", "user.email", email)
        log(f"git 提交身份：{name} <{email}>")
    return repo


def cmd_push(args: argparse.Namespace) -> int:
    repo = _setup_repo(Path(args.repo).resolve(), identity=_git_identity(args))
    tier = args.tier
    commits = commit_unit(repo, args.files or [], args.message, skip_extras=True)
    write_github_output(committed_sha=repo.committed_sha, committed="true" if commits else "false")
    if not commits and not args.push_when_clean:
        return 0

    if tier in DIRECT_TIERS:
        ok = push_direct(repo, args.branch, tier=tier)
    else:
        run_id = args.run_id or os.environ.get("GITHUB_RUN_ID") or str(int(time.time()))
        workflow = args.workflow or os.environ.get("GITHUB_WORKFLOW") or "tenshi"
        ok = push_branch(repo, args.branch, run_id, workflow)
    if not ok:
        err(
            "改动没能落库。请检查网络/令牌权限（TENSHI_BOT_ACTION_TOKEN 是否还有 "
            "Contents: write），并确认没有别的流程在长时间占着远端分支。"
        )
        return 1
    write_github_output(committed_sha=repo.committed_sha, pushed="true")
    return 0


def cmd_merge_staging(args: argparse.Namespace) -> int:
    repo = _setup_repo(Path(args.repo).resolve(), identity=_git_identity(args))
    return merge_staging(repo)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Tenshi 推送落库统一入口")
    parser.add_argument("--repo", default=".", help="tenshi 检出的工作目录")
    parser.add_argument(
        "--git-name",
        default="",
        help=f"提交身份的用户名（默认 {DEFAULT_GIT_NAME}，可用 TENSHI_GIT_NAME 覆盖）",
    )
    parser.add_argument(
        "--git-email",
        default="",
        help=f"提交身份的邮箱（默认 {DEFAULT_GIT_EMAIL}，可用 TENSHI_GIT_EMAIL 覆盖）",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    push = sub.add_parser("push", help="提交并推送本轮产生的文件")
    push.add_argument("--tier", required=True, choices=sorted(TIER_BUDGET))
    push.add_argument("--message", required=True)
    push.add_argument("--files", nargs="*", default=[])
    push.add_argument("--branch", default=DEFAULT_BRANCH)
    push.add_argument("--run-id", default="")
    push.add_argument("--workflow", default="")
    push.add_argument(
        "--push-when-clean",
        action="store_true",
        help="没有任何变更时也照样走一次 push（一般不需要）",
    )
    push.set_defaults(func=cmd_push)

    merge = sub.add_parser("merge-staging", help="把 bot-staging/* 汇流回 main")
    merge.set_defaults(func=cmd_merge_staging)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except SyncError as exc:
        err(str(exc))
        return 1
    except Exception as exc:  # noqa: BLE001 - 顶层兜底，保证 workflow 拿到非零退出码
        err(f"未预期错误：{type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
