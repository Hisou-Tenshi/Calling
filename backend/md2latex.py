"""Markdown to LaTeX conversion (rule-based, no LLM).
Also provides a compile-to-PDF helper using pdflatex if available,
or a pure-Python fallback via the reportlab library.
"""
from __future__ import annotations

import re
import subprocess
import tempfile
import os
import logging
from pathlib import Path

logger = logging.getLogger("calling.md2latex")


# ---------------------------------------------------------------------------
# MD -> LaTeX conversion
# ---------------------------------------------------------------------------

_LATEX_ESCAPE = str.maketrans({
    "&":  r"\&",
    "%":  r"\%",
    "$":  r"\$",
    "#":  r"\#",
    "_":  r"\_",
    "{": r"\{",
    "}": r"\}",
    "~":  r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
    "\\": r"\textbackslash{}",
})


def _escape(text: str) -> str:
    """Escape special LaTeX characters in plain text."""
    return text.translate(_LATEX_ESCAPE)



def _inline(text: str) -> str:
    """
    Convert inline Markdown in a line to LaTeX.
    Order matters: process code first to avoid double-escaping.
    """
    # Inline code: `code`  -> \texttt{code}
    def _repl_code(m):
        return r"\texttt{" + m.group(1).replace("{{", "{").replace("}}", "}") + "}"
    text = re.sub(r"`([^`]+)`", _repl_code, text)

    # Citation markers: ^[N]^ possibly followed by ^[,]^^[M]^ etc.
    # First merge sequences like ^[N]^^[,]^^[M]^ -> ^[N,M]^
    # Pattern: ^[X]^^[,]^^[Y]^ -> ^[X,Y]^
    def _merge_citations(t):
        # Repeatedly merge adjacent citation+comma patterns
        prev = None
        while prev != t:
            prev = t
            t = re.sub(r"\^\[([\d,\-]+)\]\^\^\[,\]\^\^\[([\d,\-]+)\]\^",
                       r"^[\1,\2]^", t)
            t = re.sub(r"\^\[([\d,\-]+)\]\^\^\[\.\]\^",
                       r"^[\1]^", t)  # remove trailing ^[.]^
        return t
    text = _merge_citations(text)
    # Convert remaining ^[N]^ to \textsuperscript{N}
    text = re.sub(r"\^\[([\d,\-]+)\]\^",
                  lambda m: r"\textsuperscript{" + m.group(1) + "}",
                  text)
    # Remove any leftover ^[.]^ or ^[,]^ punctuation markers
    text = re.sub(r"\^\[[.,]\]\^", "", text)


    # Escape the rest (outside code spans)
    # We escape char by char, but code spans are already replaced
    # Bold+italic: ***text*** or ___text___
    text = re.sub(r"\*{3}(.+?)\*{3}", lambda m: r"\textbf{\textit{" + m.group(1) + "}}", text)
    text = re.sub(r"_{3}(.+?)_{3}",   lambda m: r"\textbf{\textit{" + m.group(1) + "}}", text)
    # Bold: **text** or __text__
    text = re.sub(r"\*{2}(.+?)\*{2}", lambda m: r"\textbf{" + m.group(1) + "}", text)
    text = re.sub(r"_{2}(.+?)_{2}",   lambda m: r"\textbf{" + m.group(1) + "}", text)
    # Italic: *text* or _text_
    text = re.sub(r"\*(.+?)\*", lambda m: r"\textit{" + m.group(1) + "}", text)
    text = re.sub(r"_([^_]+)_",  lambda m: r"\textit{" + m.group(1) + "}", text)
    # Strikethrough: ~~text~~
    text = re.sub(r"~~(.+?)~~", lambda m: r"\sout{" + m.group(1) + "}", text)
    # Links: [text](url)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)",
                  lambda m: r"\href{" + m.group(2) + "}{" + m.group(1) + "}", text)
    # Images: ![alt](url)
    text = re.sub(r"!\[([^\]]*?)\]\([^)]+\)",
                  lambda m: r"[image: " + (m.group(1) or "figure") + "]", text)
    return text


def md_to_latex(md: str, *, title: str = "", author: str = "") -> str:
    """
    Convert Markdown to a complete LaTeX document.
    Handles: headings (1-6), paragraphs, bold/italic, inline code,
    fenced code blocks, ordered/unordered lists (nested),
    blockquotes, horizontal rules, Markdown tables, links, images.
    """
    lines = md.split("\n")
    out: list[str] = []
    i = 0
    n = len(lines)

    # Track list state
    list_stack: list[str] = []  # 'ul' or 'ol'

    def close_lists():
        while list_stack:
            kind = list_stack.pop()
            out.append(r"\end{" + ("itemize" if kind == "ul" else "enumerate") + "}")

    in_code_block = False
    in_table = False
    table_rows: list[list[str]] = []

    def flush_table():
        nonlocal in_table, table_rows
        if not table_rows:
            in_table = False
            return
        # Filter separator rows (all dashes)
        data_rows = [r for r in table_rows if not all(re.match(r"^-+$", c.strip()) for c in r)]
        if not data_rows:
            in_table = False
            table_rows = []
            return
        ncols = max(len(r) for r in data_rows)
        # Use equal-width p{} columns that fill linewidth
        col_w = round(0.92 / ncols, 3)
        col_spec = "|".join([f"p{{{col_w}\\linewidth}}" ] * ncols)
        out.append(r"\begin{center}")
        out.append(r"{\small")  # smaller font to help fit content
        out.append(r"\begin{tabular}{|" + col_spec + r"|}")
        out.append(r"\hline")
        for ri, row in enumerate(data_rows):
            cells = [_inline(c.strip()) for c in row]
            # pad if needed
            while len(cells) < ncols:
                cells.append("")
            if ri == 0:
                cells = [r"\textbf{" + c + "}" for c in cells]
            out.append(" & ".join(cells) + r" \\[2pt]")
            out.append(r"\hline")
        out.append(r"\end{tabular}")
        out.append(r"}")
        out.append(r"\end{center}")
        in_table = False
        table_rows = []

    while i < n:
        line = lines[i]

        # --- Fenced code block ---
        if re.match(r"^```", line):
            if not in_code_block:
                close_lists()
                lang = line[3:].strip()
                out.append(r"\begin{verbatim}")
                in_code_block = True
            else:
                out.append(r"\end{verbatim}")
                in_code_block = False
            i += 1
            continue

        if in_code_block:
            out.append(line)
            i += 1
            continue

        # --- Table line ---
        if re.match(r"^\s*\|", line):
            if not in_table:
                close_lists()
                in_table = True
                table_rows = []
            cells = [c for c in line.split("|")]
            # remove leading/trailing empty from split
            if cells and cells[0].strip() == "":
                cells = cells[1:]
            if cells and cells[-1].strip() == "":
                cells = cells[:-1]
            table_rows.append(cells)
            i += 1
            continue
        else:
            if in_table:
                flush_table()

        # --- Horizontal rule ---
        if re.match(r"^(---|===|\*\*\*)\s*$", line.strip()):
            close_lists()
            out.append(r"\noindent\rule{\linewidth}{0.4pt}")
            i += 1
            continue

        # --- Headings ---
        m = re.match(r"^(#{1,6}) (.+)$", line)
        if m:
            close_lists()
            level = len(m.group(1))
            text = _inline(m.group(2).strip())
            cmd = {
                1: r"\section",
                2: r"\subsection",
                3: r"\subsubsection",
                4: r"\paragraph",
                5: r"\subparagraph",
                6: r"\subparagraph",
            }[level]
            out.append(cmd + "{" + text + "}")
            i += 1
            continue

        # --- Blockquote ---
        if line.startswith("> ") or line.startswith(">"):
            close_lists()
            inner = line.lstrip("> ").strip()
            out.append(r"\begin{quote}")
            out.append(_inline(inner))
            out.append(r"\end{quote}")
            i += 1
            continue

        # --- Unordered list ---
        m = re.match(r"^(\s*)[-*+] (.+)$", line)
        if m:
            indent = len(m.group(1))
            depth = indent // 2
            content = _inline(m.group(2).strip())
            # adjust list depth
            while len(list_stack) > depth + 1:
                kind = list_stack.pop()
                out.append(r"\end{" + ("itemize" if kind == "ul" else "enumerate") + "}")
            if len(list_stack) <= depth:
                list_stack.append("ul")
                out.append(r"\begin{itemize}")
            out.append(r"\item " + content)
            i += 1
            continue

        # --- Ordered list ---
        m = re.match(r"^(\s*)\d+[.)]\ (.+)$", line)
        if m:
            indent = len(m.group(1))
            depth = indent // 2
            content = _inline(m.group(2).strip())
            while len(list_stack) > depth + 1:
                kind = list_stack.pop()
                out.append(r"\end{" + ("itemize" if kind == "ul" else "enumerate") + "}")
            if len(list_stack) <= depth:
                list_stack.append("ol")
                out.append(r"\begin{enumerate}")
            out.append(r"\item " + content)
            i += 1
            continue

        # --- Blank line ---
        if not line.strip():
            close_lists()
            out.append("")
            i += 1
            continue

        # --- Plain paragraph ---
        close_lists()
        out.append(_inline(line))
        i += 1

    close_lists()
    if in_code_block:
        out.append(r"\end{verbatim}")
    if in_table:
        flush_table()

    body = "\n".join(out)

    preamble_title = ""
    if title:
        preamble_title = (
            "\\title{" + _escape(title) + "}\n"
            "\\author{" + _escape(author) + "}\n"
            "\\date{\\today}\n"
            "\\maketitle\n"
        )

    latex = (
        "\\documentclass[12pt,a4paper]{article}\n"
        "\\usepackage{fontspec}\n"
        "\\usepackage{xeCJK}\n"
        "\\usepackage{amsmath,amssymb}\n"
        "\\usepackage{graphicx}\n"
        "\\usepackage[colorlinks=true,linkcolor=blue,urlcolor=blue]{hyperref}\n"
        "\\usepackage{ulem}\n"
        "\\usepackage{booktabs}\n"
        "\\usepackage[margin=2.5cm]{geometry}\n"
        "\\usepackage{parskip}\n"
        "\\setCJKmainfont{SimSun}[AutoFakeBold=2,AutoFakeSlant=0.2]\n"
        "\\setCJKsansfont{SimHei}\n"
        "\\setCJKmonofont{FangSong}\n"
        "\\begin{document}\n"
        + preamble_title
        + body + "\n"
        + "\\end{document}\n"
    )
    return latex


# ---------------------------------------------------------------------------
# PDF compilation
# ---------------------------------------------------------------------------

def compile_latex_to_pdf(latex: str) -> bytes:
    """
    Compile LaTeX source to PDF.
    Tries pdflatex first; falls back to reportlab plain-text renderer.
    Returns raw PDF bytes.
    """
    # Try pdflatex
    try:
        return _compile_pdflatex(latex)
    except Exception as e:
        logger.warning("[md2latex] pdflatex failed (%s), trying reportlab fallback", e)

    # Try reportlab
    try:
        return _compile_reportlab(latex)
    except Exception as e2:
        raise RuntimeError(
            f"PDF generation failed. pdflatex not found and reportlab unavailable. "
            f"Install pdflatex (TeX Live / MiKTeX) or run: pip install reportlab. "
            f"Details: {e2}"
        )





def _compile_pdflatex(latex: str) -> bytes:
    """Compile LaTeX to PDF using xelatex (preferred for Unicode/CJK) or pdflatex."""
    import uuid, shutil
    # Use a temp dir without spaces
    candidates = [
        Path("C:/Temp"),
        Path(os.environ.get("SystemDrive", "C:")) / "Temp",
        Path(tempfile.gettempdir()),
    ]
    base_dir = None
    for c in candidates:
        try:
            if " " not in str(c):
                c.mkdir(parents=True, exist_ok=True)
                base_dir = c
                break
        except Exception:
            pass
    if base_dir is None:
        base_dir = Path(tempfile.gettempdir())

    work_dir = base_dir / f"calling_tex_{uuid.uuid4().hex[:8]}"
    work_dir.mkdir(parents=True, exist_ok=True)
    try:
        tex_path = work_dir / "doc.tex"
        tex_path.write_text(latex, encoding="utf-8")
        tex_str = str(tex_path)
        out_str = str(work_dir)

        # Try xelatex first (full Unicode + CJK support), then pdflatex
        for engine in ["xelatex", "pdflatex"]:
            result = subprocess.run(
                [engine, "-interaction=nonstopmode",
                 "-output-directory", out_str, tex_str],
                capture_output=True,
                timeout=120,
                cwd=out_str,
            )
            pdf_path = work_dir / "doc.pdf"
            if pdf_path.exists():
                logger.info("[md2latex] compiled with %s, PDF=%d bytes", engine, pdf_path.stat().st_size)
                return pdf_path.read_bytes()
            logger.warning("[md2latex] %s failed (exit=%d)", engine, result.returncode)

        # All engines failed
        stdout = (result.stdout or b"").decode("utf-8", errors="ignore")[-800:]
        raise RuntimeError(f"xelatex/pdflatex exited {result.returncode}: {stdout}")
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def _compile_reportlab(latex: str) -> bytes:
    """Fallback: render plain-text PDF via reportlab with CJK font support."""
    import io
    try:
        from reportlab.pdfgen import canvas  # type: ignore
        from reportlab.lib.pagesizes import A4  # type: ignore
        from reportlab.lib.units import cm  # type: ignore
        from reportlab.pdfbase import pdfmetrics  # type: ignore
        from reportlab.pdfbase.ttfonts import TTFont  # type: ignore
    except ImportError:
        raise ImportError("reportlab not available. Run: pip install reportlab")

    # Register a CJK-capable font if available
    cjk_font = "Helvetica"  # fallback
    cjk_candidates = [
        (r"C:\Windows\Fonts\simsun.ttc", "SimSun"),
        (r"C:\Windows\Fonts\simhei.ttf", "SimHei"),
        (r"C:\Windows\Fonts\msyh.ttc",  "MSYaHei"),
        ("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc", "NotoSansCJK"),
        ("/System/Library/Fonts/PingFang.ttc", "PingFang"),
    ]
    for font_path, font_name in cjk_candidates:
        try:
            pdfmetrics.registerFont(TTFont(font_name, font_path, subfontIndex=0))
            cjk_font = font_name
            logger.info("[md2latex] reportlab using CJK font: %s", font_name)
            break
        except Exception:
            pass

    # Strip LaTeX commands for readable output
    text = re.sub(r"\\[a-zA-Z]+\*?\{([^}]*)\}", r"\1", latex)
    text = re.sub(r"\\[a-zA-Z]+\*?", "", text)
    text = re.sub(r"[{}]", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4
    margin = 2.5 * cm
    x = margin
    y = height - margin
    line_height = 15
    font_size = 10
    c.setFont(cjk_font, font_size)

    for para in text.split("\n"):
        for line in (para,) if len(para) < 80 else _wrap_text(para, 80):
            if y < margin:
                c.showPage()
                c.setFont(cjk_font, font_size)
                y = height - margin
            try:
                c.drawString(x, y, line)
            except Exception:
                try:
                    c.drawString(x, y, line.encode("latin-1", errors="replace").decode("latin-1"))
                except Exception:
                    pass
            y -= line_height

    c.save()
    return buf.getvalue()

def _wrap_text(text: str, width: int) -> list[str]:
    import textwrap
    return textwrap.wrap(text, width=width) or [text]
