const $ = (sel) => document.querySelector(sel);

const messagesEl = $("#messages");
const chatForm = $("#chatForm");
const promptEl = $("#prompt");
const sendBtn = $("#sendBtn");
const stopBtn = $("#stopBtn");
const clearBtn = $("#clearBtn");
const statusEl = $("#status");

const modelSelect = $("#modelSelect");
const modelCustom = $("#modelCustom");
const ragToggle = $("#ragToggle");
const forceSearchToggle = $("#forceSearchToggle");
const fileInput = $("#fileInput");
const uploadBtn = $("#uploadBtn");
const uploadListEl = $("#uploadList");

const newConvBtn = $("#newConvBtn");
const convListEl = $("#convList");

let conversationId = null;
let messages = []; // [{role:'user'|'assistant', content:string}]
let uploadedFiles = []; // ["data/uploads/xxx"]
let conversationsCache = [];
let chatBusy = false;
let chatAbortController = null;

function setStatus(text) {
  statusEl.textContent = text || "";
}

function escapeHtml(text) {
  return String(text || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function renderInlineMarkdown(src) {
  let out = escapeHtml(src || "");
  out = out.replace(/`([^`\n]+)`/g, "<code>$1</code>");
  out = out.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  out = out.replace(/\*([^*\n]+)\*/g, "<em>$1</em>");
  out = out.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noreferrer">$1</a>');
  return out;
}

function renderCodeLines(lines) {
  return lines
    .map((line, idx) => {
      const cls = idx % 2 === 0 ? "code-line blue" : "code-line pink";
      const body = line.length ? escapeHtml(line) : "&nbsp;";
      return `<span class="${cls}">${body}</span>`;
    })
    .join("");
}

function renderUserTextLines(lines) {
  return lines
    .map((line) => `<span class="user-line">${escapeHtml(line.length ? line : " ")}</span>`)
    .join("");
}

function renderMarkdownToHtml(mdText) {
  const text = String(mdText || "");
  const lines = text.split(/\r?\n/);
  const html = [];
  let i = 0;
  let para = [];

  function flushPara() {
    if (!para.length) return;
    html.push(`<p>${renderInlineMarkdown(para.join(" ").trim())}</p>`);
    para = [];
  }

  while (i < lines.length) {
    const line = lines[i] || "";
    const trimmed = line.trim();
    if (!trimmed) {
      flushPara();
      i += 1;
      continue;
    }

    const codeFence = trimmed.match(/^```(\w+)?$/);
    if (codeFence) {
      flushPara();
      const lang = codeFence[1] || "";
      i += 1;
      const buf = [];
      while (i < lines.length && !String(lines[i] || "").trim().startsWith("```")) {
        buf.push(lines[i] || "");
        i += 1;
      }
      if (i < lines.length) i += 1;
      const codeText = buf.join("\n");
      const fullCodeHtml = renderCodeLines(buf);
      if (buf.length > 5) {
        html.push(
          `<div class="code-block-wrap collapsed">` +
          `<button type="button" class="code-copy-btn" data-code="${encodeURIComponent(codeText)}">复制</button>` +
          `<pre class="code-pre"><code>${fullCodeHtml}</code></pre>` +
          `<button type="button" class="code-toggle-btn" data-open="0" data-expand-label="${escapeHtml(`展开剩余 ${buf.length - 5} 行${lang ? ` · ${lang}` : ""}`)}">展开剩余 ${buf.length - 5} 行${lang ? ` · ${escapeHtml(lang)}` : ""}</button>` +
          `</div>`
        );
      } else {
        html.push(
          `<div class="code-block-wrap">` +
          `<button type="button" class="code-copy-btn" data-code="${encodeURIComponent(codeText)}">复制</button>` +
          `<pre class="code-pre"><code>${fullCodeHtml}</code></pre>` +
          `</div>`
        );
      }
      continue;
    }

    if (/^\s*---+\s*$/.test(line)) {
      flushPara();
      html.push("<hr />");
      i += 1;
      continue;
    }

    const h = line.match(/^(#{1,6})\s+(.+)$/);
    if (h) {
      flushPara();
      const level = h[1].length;
      html.push(`<h${level}>${renderInlineMarkdown(h[2])}</h${level}>`);
      i += 1;
      continue;
    }

    const bq = line.match(/^\s*>\s?(.+)$/);
    if (bq) {
      flushPara();
      html.push(`<blockquote>${renderInlineMarkdown(bq[1])}</blockquote>`);
      i += 1;
      continue;
    }

    const ul = line.match(/^\s*[-*]\s+(.+)$/);
    if (ul) {
      flushPara();
      const items = [];
      while (i < lines.length) {
        const m = String(lines[i] || "").match(/^\s*[-*]\s+(.+)$/);
        if (!m) break;
        items.push(`<li>${renderInlineMarkdown(m[1])}</li>`);
        i += 1;
      }
      html.push(`<ul>${items.join("")}</ul>`);
      continue;
    }

    const ol = line.match(/^\s*\d+\.\s+(.+)$/);
    if (ol) {
      flushPara();
      const items = [];
      while (i < lines.length) {
        const m = String(lines[i] || "").match(/^\s*\d+\.\s+(.+)$/);
        if (!m) break;
        items.push(`<li>${renderInlineMarkdown(m[1])}</li>`);
        i += 1;
      }
      html.push(`<ol>${items.join("")}</ol>`);
      continue;
    }

    para.push(line);
    i += 1;
  }

  flushPara();
  return html.join("\n");
}

function isCurrentConversationEmpty() {
  return (messages || []).length === 0 && (uploadedFiles || []).length === 0;
}

function renderMessages() {
  messagesEl.innerHTML = "";
  for (let i = 0; i < messages.length; i++) {
    const m = messages[i];
    const div = document.createElement("div");
    div.className = `msg ${m.role}`;
    div.dataset.index = String(i);
    const meta = document.createElement("div");
    meta.className = "msg-meta";
    if (m.role === "user") {
      meta.textContent = "You";
    } else {
      meta.textContent = (m.model || "").trim() ? m.model : "Model";
    }

    const hasThinking = m.role === "assistant" && (m.thinking || "").trim();
    if (hasThinking) {
      const thinkingWrap = document.createElement("details");
      thinkingWrap.className = "msg-thinking-wrap";
      thinkingWrap.open = false;
      const summary = document.createElement("summary");
      summary.textContent = "模型思考（默认折叠）";
      const thinking = document.createElement("div");
      thinking.className = "msg-thinking";
      thinking.textContent = m.thinking || "";
      thinkingWrap.appendChild(summary);
      thinkingWrap.appendChild(thinking);
      div.appendChild(meta);
      div.appendChild(thinkingWrap);
    } else {
      div.appendChild(meta);
    }

    const content = document.createElement("div");
    content.className = "msg-content";
    if (m.role === "assistant") {
      content.innerHTML = renderMarkdownToHtml(m.content || "");
    } else {
      const userText = String(m.content || "");
      const userLines = userText.split(/\r?\n/);
      if (userLines.length > 3) {
        content.innerHTML = `
          <div class="user-text-wrap collapsed">
            <div class="user-text-lines">${renderUserTextLines(userLines)}</div>
            <button type="button" class="user-toggle-btn" data-open="0">展开剩余 ${userLines.length - 3} 行</button>
          </div>
        `;
      } else {
        content.textContent = userText;
      }
    }
    div.appendChild(content);

    if (m.role === "assistant") {
      const actions = document.createElement("div");
      actions.className = "msg-actions";
      actions.innerHTML = `
        <button type="button" class="btn msg-action" data-act="copy-md">复制MD</button>
        <button type="button" class="btn msg-action" data-act="copy-plain">复制文本</button>
        <button type="button" class="btn msg-action" data-act="retry">重试</button>
        <button type="button" class="btn msg-action" data-act="retry-remodel">更换模型重试</button>
        <button type="button" class="btn msg-action" data-act="retry-verbose">详尽一点</button>
        <button type="button" class="btn msg-action" data-act="retry-brief">简短一点</button>
        <button type="button" class="btn msg-action" data-act="retry-structured">更格式化</button>
        <button type="button" class="btn msg-action" data-act="retry-natural">更自然语言</button>
        <button type="button" class="btn msg-action" data-act="edit-fork">修改并Fork</button>
        ${m.interrupted ? '<button type="button" class="btn msg-action primary" data-act="continue">继续输出</button>' : ""}
      `;
      div.appendChild(actions);
    }
    messagesEl.appendChild(div);
  }
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function pillForEmbedded(embedded) {
  const span = document.createElement("span");
  span.className = "pill " + (embedded ? "ok" : "no");
  span.textContent = embedded ? "embedded" : "saved";
  return span;
}

function renderUploadsFromPaths(paths) {
  uploadListEl.innerHTML = "";
  for (const p of paths || []) {
    const item = document.createElement("div");
    item.className = "upload-item";

    const left = document.createElement("div");
    left.className = "left";

    const name = document.createElement("div");
    name.className = "name";
    name.textContent = p.split("/").pop() || p;

    const path = document.createElement("div");
    path.className = "path";
    path.textContent = p;

    left.appendChild(name);
    left.appendChild(path);

    // We don't persist embedding status per file in the UI; show "saved".
    const right = pillForEmbedded(false);

    item.appendChild(left);
    item.appendChild(right);
    uploadListEl.appendChild(item);
  }
}

function getSelectedModel() {
  const custom = (modelCustom.value || "").trim();
  if (custom) return custom;
  return modelSelect.value || "";
}

async function loadModels() {
  try {
    const res = await fetch("/api/models");
    if (!res.ok) throw new Error("Failed to fetch /api/models");
    const data = await res.json();
    const options = data.options || [];
    modelSelect.innerHTML = "";
    for (const opt of options) {
      const o = document.createElement("option");
      o.value = opt;
      o.textContent = opt;
      modelSelect.appendChild(o);
    }
    if (data.default) modelSelect.value = data.default;
  } catch (e) {
    setStatus("Model list unavailable; you can still type a model id manually.");
  }
}

function renderConversationList(conversations) {
  convListEl.innerHTML = "";
  if (!conversations || conversations.length === 0) {
    const empty = document.createElement("div");
    empty.className = "hint";
    empty.textContent = "No conversations yet.";
    convListEl.appendChild(empty);
    return;
  }

  for (const c of conversations) {
    const row = document.createElement("div");
    row.className = "conv-item" + (c.conversation_id === conversationId ? " active" : "");
    row.innerHTML = `
      <div class="conv-row">
        <div class="conv-left">
          <div class="conv-title">${c.title || "Untitled"}</div>
          <div class="conv-meta">${c.message_count || 0} msgs · ${c.uploaded_count || 0} files</div>
        </div>
        <button type="button" class="conv-del" aria-label="Delete conversation">×</button>
      </div>
    `;
    const delBtn = row.querySelector(".conv-del");
    row.addEventListener("click", async () => {
      await selectConversation(c.conversation_id);
    });
    if (delBtn) {
      delBtn.addEventListener("click", async (e) => {
        e.stopPropagation();
        await deleteConversation(c.conversation_id);
      });
    }
    convListEl.appendChild(row);
  }
}

async function refreshConversationList() {
  try {
    const res = await fetch("/api/conversations");
    if (!res.ok) return;
    const data = await res.json();
    conversationsCache = data.conversations || [];
    renderConversationList(conversationsCache);
  } catch {
    // ignore
  }
}

async function selectConversation(cid) {
  if (!cid) return;
  conversationId = cid;
  try {
    const res = await fetch(`/api/conversations/${encodeURIComponent(cid)}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Load conversation failed");

    messages = data.messages || [];
    uploadedFiles = data.uploaded_files || [];
    renderMessages();
    renderUploadsFromPaths(uploadedFiles);
    setStatus(`Switched: ${data.title || "chat"}`);
    renderConversationList(conversationsCache);
  } catch (e) {
    setStatus(String(e?.message || e));
  }
}

async function createNewConversation() {
  if (conversationId && isCurrentConversationEmpty()) {
    setStatus("Already in an empty chat. New chat is disabled.");
    return;
  }
  try {
    const res = await fetch("/api/conversations/new", { method: "POST" });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Create conversation failed");
    conversationId = data.conversation_id;
    messages = [];
    uploadedFiles = [];
    renderMessages();
    renderUploadsFromPaths([]);
    setStatus("New chat created.");
    await refreshConversationList();
  } catch (e) {
    setStatus(String(e?.message || e));
  }
}

async function ensureConversationSelected() {
  if (conversationId) return;
  await refreshConversationList();
  if (!conversationsCache || conversationsCache.length === 0) {
    await createNewConversation();
  } else {
    await selectConversation(conversationsCache[0].conversation_id);
  }
}

async function uploadFiles() {
  const files = Array.from(fileInput.files || []);
  if (!files.length) return;
  await ensureConversationSelected();
  if (!conversationId) return;

  setStatus("Uploading...");
  sendBtn.disabled = true;
  uploadBtn.disabled = true;

  const form = new FormData();
  form.set("conversation_id", conversationId);
  for (const f of files) form.append("files", f);
  form.set("rag_enable", ragToggle.checked ? "true" : "false");

  try {
    const res = await fetch("/api/upload", {
      method: "POST",
      body: form,
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Upload failed");

    const uploaded = data.uploaded || [];
    for (const u of uploaded) {
      if (u.file_path) uploadedFiles.push(u.file_path);
    }

    renderUploadsFromPaths(uploadedFiles);
    setStatus(`Uploaded ${uploaded.length} file(s).`);
    await refreshConversationList();
  } catch (e) {
    setStatus(String(e?.message || e));
  } finally {
    sendBtn.disabled = false;
    uploadBtn.disabled = false;
    fileInput.value = "";
  }
}

async function sendMessage(opts = {}) {
  if (chatBusy) return;
  const model = getSelectedModel();
  if (!model) {
    setStatus("Please select or type a model id.");
    return;
  }
  await ensureConversationSelected();
  if (!conversationId) return;

  const rag_enabled = !!ragToggle.checked;
  const force_web_search = !!forceSearchToggle.checked;

  const sourceMessages = Array.isArray(opts.messagesOverride) ? opts.messagesOverride : messages;
  const body = {
    conversation_id: conversationId,
    model,
    messages: sourceMessages,
    rag_enabled,
    force_web_search,
    uploaded_files: uploadedFiles,
  };
  if (opts.continueFrom) body.continue_from = opts.continueFrom;

  setStatus("Waiting for assistant...");
  sendBtn.disabled = true;
  if (stopBtn) stopBtn.style.display = "";
  chatBusy = true;
  chatAbortController = new AbortController();
  try {
    // Pre-insert an assistant placeholder and stream into it.
    const assistantMsg = { role: "assistant", content: "", model, thinking: "" };
    messages = sourceMessages.slice();
    messages.push(assistantMsg);
    renderMessages();

    const res = await fetch("/api/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: chatAbortController.signal,
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Chat failed");
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let donePayload = null;

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split("\n\n");
      buffer = parts.pop() || "";

      for (const part of parts) {
        const eventMatch = part.match(/^event: ([\w_]+)/m);
        const dataMatch = part.match(/^data: (.+)$/m);
        if (!eventMatch || !dataMatch) continue;
        let data;
        try { data = JSON.parse(dataMatch[1]); } catch { continue; }
        const evtName = eventMatch[1];

        if (evtName === "status") {
          setStatus(data.message || "Assistant is thinking...");
        } else if (evtName === "thinking_delta") {
          if (data.transient) {
            setStatus(data.text || "Thinking...");
          } else {
            assistantMsg.thinking = (assistantMsg.thinking || "") + (data.text || "");
            renderMessages();
            setStatus("Received thinking stream, waiting for final answer...");
          }
        } else if (evtName === "answer_delta") {
          assistantMsg.content = (assistantMsg.content || "") + (data.text || "");
          renderMessages();
          setStatus("Streaming answer...");
        } else if (evtName === "done") {
          donePayload = data || {};
        } else if (evtName === "error") {
          throw new Error(data.detail || "Chat failed");
        }
      }
    }

    if (!donePayload) throw new Error("Stream ended unexpectedly.");
    assistantMsg.content = donePayload.assistant || assistantMsg.content || "";
    assistantMsg.thinking = donePayload.thinking || assistantMsg.thinking || "";
    assistantMsg.interrupted = false;
    renderMessages();

    if (forceSearchToggle.checked && donePayload.web_search_called) {
      setStatus("web_search used.");
    } else if (forceSearchToggle.checked && !donePayload.web_search_called) {
      setStatus("web_search not detected (model may have answered anyway).");
    } else {
      setStatus("Done.");
    }
    await refreshConversationList();
  } catch (e) {
    if (e?.name === "AbortError") {
      const lastAborted = messages[messages.length - 1];
      if (lastAborted && lastAborted.role === "assistant" && (lastAborted.content || "").trim()) {
        lastAborted.interrupted = true;
      }
      renderMessages();
      setStatus("Output interrupted.");
      return;
    }
    const last = messages[messages.length - 1];
    if (last && last.role === "assistant" && !last.content) {
      messages.pop();
      renderMessages();
    }
    setStatus(String(e?.message || e));
  } finally {
    sendBtn.disabled = false;
    if (stopBtn) stopBtn.style.display = "none";
    chatAbortController = null;
    chatBusy = false;
  }
}

chatForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const text = (promptEl.value || "").trim();
  if (!text) return;
  await ensureConversationSelected();
  if (!conversationId) return;

  messages.push({ role: "user", content: text });
  promptEl.value = "";
  renderMessages();

  await sendMessage();
});

async function runRetry(assistantIndex, retryInstruction) {
  if (chatBusy) return;
  const userIndex = assistantIndex - 1;
  if (assistantIndex < 0 || userIndex < 0 || messages[userIndex]?.role !== "user") {
    setStatus("Cannot retry this message.");
    return;
  }
  const branch = messages.slice(0, assistantIndex);
  if (retryInstruction) {
    branch.push({ role: "user", content: retryInstruction });
  }
  await sendMessage({ messagesOverride: branch });
}

async function forkFromEditedPrompt(assistantIndex) {
  const userIndex = assistantIndex - 1;
  if (assistantIndex < 0 || userIndex < 0 || messages[userIndex]?.role !== "user") {
    setStatus("请选择包含 user->assistant 的轮次。");
    return;
  }
  const oldPrompt = messages[userIndex]?.content || "";
  const edited = window.prompt("修改该轮提示词（将从这里 fork 新会话）", oldPrompt);
  if (edited == null) return;
  const branch = messages.slice(0, userIndex);
  branch.push({ role: "user", content: edited.trim() });

  try {
    const res = await fetch("/api/conversations/fork", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        conversation_id: conversationId,
        messages: branch,
        uploaded_files: uploadedFiles,
      }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Fork failed");
    conversationId = data.conversation_id;
    messages = branch;
    renderMessages();
    await refreshConversationList();
    await sendMessage();
  } catch (e) {
    setStatus(String(e?.message || e));
  }
}

messagesEl.addEventListener("click", async (e) => {
  const userToggleBtn = e.target.closest(".user-toggle-btn");
  if (userToggleBtn) {
    const userWrap = userToggleBtn.closest(".user-text-wrap");
    if (!userWrap) return;
    const open = userToggleBtn.dataset.open === "1";
    if (open) {
      userWrap.classList.add("collapsed");
      userToggleBtn.dataset.open = "0";
      const total = userWrap.querySelectorAll(".user-line").length;
      userToggleBtn.textContent = `展开剩余 ${Math.max(0, total - 3)} 行`;
    } else {
      userWrap.classList.remove("collapsed");
      userToggleBtn.dataset.open = "1";
      userToggleBtn.textContent = "向上折叠";
    }
    return;
  }

  const toggleBtn = e.target.closest(".code-toggle-btn");
  if (toggleBtn) {
    const wrap = toggleBtn.closest(".code-block-wrap");
    if (!wrap) return;
    const open = toggleBtn.dataset.open === "1";
    if (open) {
      wrap.classList.add("collapsed");
      toggleBtn.dataset.open = "0";
      toggleBtn.textContent = toggleBtn.dataset.expandLabel || "展开剩余内容";
    } else {
      wrap.classList.remove("collapsed");
      toggleBtn.dataset.open = "1";
      toggleBtn.textContent = "向上折叠";
    }
    return;
  }

  const copyBtn = e.target.closest(".code-copy-btn");
  if (copyBtn) {
    const raw = decodeURIComponent(copyBtn.dataset.code || "");
    await navigator.clipboard.writeText(raw);
    copyBtn.textContent = "已复制";
    setTimeout(() => { copyBtn.textContent = "复制"; }, 1200);
    return;
  }

  const btn = e.target.closest(".msg-action");
  if (!btn) return;
  const wrap = btn.closest(".msg");
  if (!wrap) return;
  const idx = Number(wrap.dataset.index || -1);
  if (!Number.isInteger(idx) || idx < 0) return;
  const msg = messages[idx] || {};
  const act = btn.dataset.act;

  if (act === "copy-md") {
    await navigator.clipboard.writeText(msg.content || "");
    setStatus("Copied markdown.");
    return;
  }
  if (act === "copy-plain") {
    const tmp = document.createElement("div");
    tmp.innerHTML = renderMarkdownToHtml(msg.content || "");
    await navigator.clipboard.writeText(tmp.textContent || "");
    setStatus("Copied plaintext.");
    return;
  }
  if (act === "retry") return runRetry(idx, "");
  if (act === "retry-remodel") {
    const currentModel = getSelectedModel();
    const oldModel = (msg.model || "").trim();
    if (!currentModel) {
      setStatus("请先在右侧选择模型。");
      return;
    }
    if (oldModel && oldModel === currentModel) {
      setStatus("当前选择模型与原回复相同；如需换模型重试，请先在右侧切换模型。");
    } else {
      setStatus(`将使用新模型重试：${currentModel}`);
    }
    return runRetry(idx, "");
  }
  if (act === "retry-verbose") return runRetry(idx, "请在保持正确性的前提下详尽一点。");
  if (act === "retry-brief") return runRetry(idx, "请更简短，控制在核心要点。");
  if (act === "retry-structured") return runRetry(idx, "请用更结构化的格式回答（标题 + 要点列表）。");
  if (act === "retry-natural") return runRetry(idx, "请改成更自然、口语化但专业的表达。");
  if (act === "edit-fork") return forkFromEditedPrompt(idx);
  if (act === "continue") {
    const partial = msg.content || "";
    if (!partial.trim()) {
      setStatus("No partial response to continue.");
      return;
    }
    const branch = messages.slice(0, idx + 1);
    const tail = partial.slice(-800);
    const continueHint = `Continue your previous answer from the exact point where it stopped. Do not restart or repeat earlier sections.\n\nLast emitted tail:\n${tail}`;
    await sendMessage({ messagesOverride: branch, continueFrom: continueHint });
    return;
  }
});

if (stopBtn) {
  stopBtn.addEventListener("click", () => {
    if (chatAbortController) chatAbortController.abort();
  });
}

newConvBtn.addEventListener("click", async () => {
  await createNewConversation();
});

clearBtn.addEventListener("click", async () => {
  if (conversationId && isCurrentConversationEmpty()) {
    setStatus("Already empty. Clear does nothing.");
    return;
  }
  await createNewConversation();
});

uploadBtn.addEventListener("click", async () => {
  await uploadFiles();
});

async function deleteConversation(cid) {
  if (!cid) return;
  try {
    const res = await fetch(`/api/conversations/${encodeURIComponent(cid)}`, { method: "DELETE" });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || "Delete failed");

    // If deleting current conversation, reset selection.
    if (conversationId === cid) {
      conversationId = null;
      messages = [];
      uploadedFiles = [];
      renderMessages();
      renderUploadsFromPaths([]);
    }

    await refreshConversationList();

    // If nothing is selected, choose next or create a new one if needed.
    await ensureConversationSelected();
  } catch (e) {
    setStatus(String(e?.message || e));
  }
}

loadModels();
renderMessages();
renderUploadsFromPaths([]);
refreshConversationList();

// ============================================================
// Tab switching
// ============================================================
document.querySelectorAll('.tab').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach(t => {
      t.classList.remove('active');
      t.setAttribute('aria-selected', 'false');
    });
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
    btn.classList.add('active');
    btn.setAttribute('aria-selected', 'true');
    const target = btn.dataset.tab;
    const panel = document.getElementById('tab-' + target);
    if (panel) panel.classList.add('active');
  });
});

// ============================================================
// Translate tab
// ============================================================
const trFileInput    = document.getElementById('trFileInput');
const trModelSelect  = document.getElementById('trModelSelect');
const trModelCustom  = document.getElementById('trModelCustom');
const trTargetLang   = document.getElementById('trTargetLang');
const trSourceLang   = document.getElementById('trSourceLang');
const trSepPreset    = document.getElementById('trSepPreset');
const trCustomSep    = document.getElementById('trCustomSep');
const trCustomSepField = document.getElementById('trCustomSepField');
const trSeparatorOpts  = document.getElementById('trSeparatorOptions');
const trLlmSplitOpts   = document.getElementById('trLlmSplitOptions');
const trLlmSplitModel  = document.getElementById('trLlmSplitModel');
const trParentMax    = document.getElementById('trParentMax');
const trChildMax     = document.getElementById('trChildMax');
const trStartBtn     = document.getElementById('trStartBtn');
const trStatusEl     = document.getElementById('trStatus');
const trOutputEl     = document.getElementById('trOutput');
const trCopyBtn      = document.getElementById('trCopyBtn');
const trDownloadBtn  = document.getElementById('trDownloadBtn');
const trChunkInfo    = document.getElementById('trChunkInfo');

function trGetModel() {
  return (trModelCustom.value || '').trim() || trModelSelect.value || '';
}

async function loadTranslateLanguages() {
  try {
    const res = await fetch('/api/translate/languages');
    if (!res.ok) return;
    const data = await res.json();
    const langs = data.languages || [];
    [trTargetLang, trSourceLang].forEach((sel, idx) => {
      const existing = Array.from(sel.options).map(o => o.value);
      for (const lang of langs) {
        if (!existing.includes(lang)) {
          const o = document.createElement('option');
          o.value = lang;
          o.textContent = lang;
          sel.appendChild(o);
        }
      }
    });
    trTargetLang.value = 'Chinese (Simplified)';
  } catch {}
}

async function populateTrModelSelect() {
  try {
    const res = await fetch('/api/models');
    if (!res.ok) return;
    const data = await res.json();
    trModelSelect.innerHTML = '';
    for (const opt of (data.options || [])) {
      const o = document.createElement('option');
      o.value = opt; o.textContent = opt;
      trModelSelect.appendChild(o);
    }
    if (data.default) trModelSelect.value = data.default;
  } catch {}
}

// show/hide split option panes
document.querySelectorAll('input[name="trSplitMode"]').forEach(radio => {
  radio.addEventListener('change', () => {
    const isLlm = radio.value === 'llm' && radio.checked;
    trSeparatorOpts.style.display = isLlm ? 'none' : '';
    trLlmSplitOpts.style.display  = isLlm ? '' : 'none';
  });
});

trSepPreset.addEventListener('change', () => {
  trCustomSepField.style.display = trSepPreset.value === 'custom' ? '' : 'none';
});

let trLastResult = null;
let trCurrentJobId = null;
let trAbortController = null;

const trAbortBtn = document.getElementById('trAbortBtn');
const trDownloadTexBtn = document.getElementById('trDownloadTexBtn');
const trDownloadPdfBtn = document.getElementById('trDownloadPdfBtn');

function trEnableOutputBtns() {
  trCopyBtn.disabled = false;
  trDownloadBtn.disabled = false;
  trDownloadTexBtn.disabled = false;
  trDownloadPdfBtn.disabled = false;
}

function trDisableOutputBtns() {
  trDisableOutputBtns();
  trDownloadTexBtn.disabled = true;
  trDownloadPdfBtn.disabled = true;
}

function trSetProgress(percent, label) {
  const bar = document.getElementById('trProgressBar');
  const wrap = document.getElementById('trProgressWrap');
  const lbl = document.getElementById('trProgressLabel');
  if (wrap) wrap.style.display = percent >= 0 ? '' : 'none';
  if (bar) bar.style.width = Math.max(0, Math.min(100, percent)) + '%';
  if (lbl) lbl.textContent = label || '';
}

function trResetUI() {
  trStartBtn.disabled = false;
  if (trAbortBtn) trAbortBtn.style.display = 'none';
  trSetProgress(-1, '');
}

trStartBtn.addEventListener('click', async () => {
  const file = trFileInput.files && trFileInput.files[0];
  if (!file) { trStatusEl.textContent = 'Please select a file.'; return; }
  const model = trGetModel();
  if (!model) { trStatusEl.textContent = 'Please select a model.'; return; }

  const jobId = 'job_' + Date.now().toString(36);
  trCurrentJobId = jobId;

  const splitMode = document.querySelector('input[name="trSplitMode"]:checked').value;
  const form = new FormData();
  form.append('file', file);
  form.append('model', model);
  form.append('target_lang', trTargetLang.value || 'English');
  form.append('source_lang', trSourceLang.value || '');
  form.append('split_mode', splitMode);
  form.append('separator_preset', trSepPreset.value || 'paragraph');
  form.append('custom_separators', trCustomSep.value || '');
  form.append('parent_max_chars', trParentMax.value || '3000');
  form.append('child_max_chars', trChildMax.value || '800');
  form.append('llm_split_model', trLlmSplitModel.value || '');
  form.append('job_id', jobId);

  trStartBtn.disabled = true;
  if (trAbortBtn) trAbortBtn.style.display = '';
  trCopyBtn.disabled = true;
  trDownloadBtn.disabled = true;
  trOutputEl.textContent = '';
  trChunkInfo.textContent = '';
  trStatusEl.textContent = 'Connecting...';
  trSetProgress(0, 'Starting...');

  trAbortController = new AbortController();

  try {
    const res = await fetch('/api/translate/stream', {
      method: 'POST',
      body: form,
      signal: trAbortController.signal,
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.error || `HTTP ${res.status}`);
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let accumulatedText = '';
    let totalChunks = 0;

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      // Parse SSE events from buffer
      const parts = buffer.split('\n\n');
      buffer = parts.pop(); // keep incomplete last part

      for (const part of parts) {
        const eventMatch = part.match(/^event: (\w+)/);
        const dataMatch = part.match(/^data: (.+)$/m);
        if (!eventMatch || !dataMatch) continue;
        const evtName = eventMatch[1];
        let data;
        try { data = JSON.parse(dataMatch[1]); } catch { continue; }

        if (evtName === 'start') {
          trStatusEl.textContent = `Translating: ${data.filename}`;
        } else if (evtName === 'progress') {
          if (data.stage === 'extracted') {
            trSetProgress(2, `Extracted ${data.chars} chars, splitting...`);
          } else if (data.stage === 'split') {
            totalChunks = data.total;
            trSetProgress(5, `Split into ${data.total} chunks`);
          }
        } else if (evtName === 'chunk_start') {
          const pct = 5 + (data.index / data.total) * 90;
          const skipLabel = data.skipped ? ' [refs — verbatim]' : '';
          trSetProgress(pct, `Chunk ${data.index + 1}/${data.total}${skipLabel}`);
          trStatusEl.textContent = data.skipped
            ? `Chunk ${data.index + 1}/${data.total} — references section, passing through verbatim`
            : `Translating chunk ${data.index + 1}/${data.total} (${data.chars} chars)`;
        } else if (evtName === 'chunk_done') {
          const pct = 5 + ((data.index + 1) / data.total) * 90;
          trSetProgress(pct, `${data.index + 1}/${data.total} done (${data.percent}%)`);
          accumulatedText += (accumulatedText ? '\n\n' : '') + data.text;
          trOutputEl.textContent = accumulatedText;
          trOutputEl.scrollTop = trOutputEl.scrollHeight;
          trChunkInfo.textContent = `${data.index + 1}/${data.total} chunks`;
        } else if (evtName === 'done') {
          trLastResult = data;
          trOutputEl.textContent = data.translated_text || '';
          trChunkInfo.textContent = `${data.chunks_total} chunk(s) translated`;
          trStatusEl.textContent = 'Done.';
          trSetProgress(100, 'Complete');
          trEnableOutputBtns();
          setTimeout(() => trSetProgress(-1, ''), 2000);
        } else if (evtName === 'aborted') {
          trStatusEl.textContent = `Aborted after ${data.done}/${data.total} chunks.`;
          if (accumulatedText) {
            trLastResult = { translated_text: accumulatedText, filename: file.name };
            trEnableOutputBtns();
          }
          trSetProgress(-1, '');
        } else if (evtName === 'error') {
          trStatusEl.textContent = 'Error: ' + (data.message || 'unknown');
          trSetProgress(-1, '');
        }
      }
    }
  } catch (e) {
    if (e.name === 'AbortError') {
      trStatusEl.textContent = 'Aborted.';
      if (accumulatedText) {
        trLastResult = { translated_text: accumulatedText, filename: (trFileInput.files[0] || {}).name || 'translated' };
        trEnableOutputBtns();
      }
    } else {
      trStatusEl.textContent = 'Error: ' + (e.message || String(e));
    }
    trSetProgress(-1, '');
  } finally {
    trResetUI();
    trCurrentJobId = null;
    trAbortController = null;
  }
});

if (trAbortBtn) {
  trAbortBtn.addEventListener('click', async () => {
    if (trCurrentJobId) {
      try {
        await fetch('/api/translate/abort/' + trCurrentJobId, { method: 'POST' });
      } catch {}
    }
    if (trAbortController) trAbortController.abort();
    trStatusEl.textContent = 'Aborting...';
    trAbortBtn.disabled = true;
  });
}


trDownloadTexBtn.addEventListener('click', async () => {
  const md = trOutputEl.textContent || '';
  if (!md) return;
  trDownloadTexBtn.textContent = 'Converting...';
  trDownloadTexBtn.disabled = true;
  try {
    const origName = (trLastResult && trLastResult.filename) || 'translated';
    const base = origName.replace(/\.[^.]+$/, '');
    const res = await fetch('/api/convert/tex', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ md, title: base }),
    });
    const data = await res.json();
    if (!res.ok || data.error) throw new Error(data.error || 'Conversion failed');
    const blob = new Blob([data.latex], { type: 'application/x-latex' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = base + '.tex';
    a.click();
    URL.revokeObjectURL(url);
  } catch (e) {
    trStatusEl.textContent = 'TeX error: ' + (e.message || String(e));
  } finally {
    trDownloadTexBtn.textContent = 'Download .tex';
    trDownloadTexBtn.disabled = false;
  }
});

trDownloadPdfBtn.addEventListener('click', async () => {
  const md = trOutputEl.textContent || '';
  if (!md) return;
  trDownloadPdfBtn.textContent = 'Compiling...';
  trDownloadPdfBtn.disabled = true;
  trStatusEl.textContent = 'Compiling PDF (this may take a moment)...';
  try {
    const origName = (trLastResult && trLastResult.filename) || 'translated';
    const base = origName.replace(/\.[^.]+$/, '');
    const res = await fetch('/api/convert/pdf', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ md, title: base }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.error || `HTTP ${res.status}`);
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = base + '.pdf';
    a.click();
    URL.revokeObjectURL(url);
    trStatusEl.textContent = 'PDF downloaded.';
  } catch (e) {
    trStatusEl.textContent = 'PDF error: ' + (e.message || String(e));
  } finally {
    trDownloadPdfBtn.textContent = 'Download .pdf';
    trDownloadPdfBtn.disabled = false;
  }
});

trCopyBtn.addEventListener('click', async () => {
  const text = trOutputEl.textContent || '';
  try {
    await navigator.clipboard.writeText(text);
    trCopyBtn.textContent = 'Copied!';
    setTimeout(() => { trCopyBtn.textContent = 'Copy'; }, 1500);
  } catch { trStatusEl.textContent = 'Copy failed.'; }
});

trDownloadBtn.addEventListener('click', () => {
  const text = trOutputEl.textContent || '';
  if (!text) return;
  const origName = (trLastResult && trLastResult.filename) || 'translated';
  const base = origName.replace(/\.[^.]+$/, '');
  const blob = new Blob([text], { type: 'text/markdown' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = base + '_translated.md';
  a.click();
  URL.revokeObjectURL(url);
});

populateTrModelSelect();
loadTranslateLanguages();

// ============================================================
// Floating log panel
// ============================================================
const logPanel      = document.getElementById('logPanel');
const logBody       = document.getElementById('logBody');
const logToggleBtn  = document.getElementById('logToggleBtn');
const logCloseBtn   = document.getElementById('logCloseBtn');
const logClearBtn   = document.getElementById('logClearBtn');
const shutdownBtn   = document.getElementById('serverShutdownBtn');

let logEs = null;
let logAutoScroll = true;
const LOG_MAX_LINES = 500;

function logLevelClass(level) {
  if (level === 'ERROR' || level === 'CRITICAL') return 'log-error';
  if (level === 'WARNING') return 'log-warn';
  if (level === 'DEBUG') return 'log-debug';
  return 'log-info';
}

function appendLogLine(line, level) {
  const el = document.createElement('div');
  el.className = 'log-line ' + logLevelClass(level || 'INFO');
  el.textContent = line;
  logBody.appendChild(el);
  // trim old lines
  while (logBody.children.length > LOG_MAX_LINES) {
    logBody.removeChild(logBody.firstChild);
  }
  if (logAutoScroll) logBody.scrollTop = logBody.scrollHeight;
}

function startLogStream() {
  if (logEs) return;
  logEs = new EventSource('/api/logs');
  logEs.onmessage = (e) => {
    try {
      const data = JSON.parse(e.data);
      appendLogLine(data.line, data.level);
    } catch {}
  };
  logEs.onerror = () => {
    appendLogLine('[log stream disconnected]', 'WARNING');
    logEs.close();
    logEs = null;
    // reconnect after 3s
    setTimeout(() => { if (logPanel.style.display !== 'none') startLogStream(); }, 3000);
  };
}

function stopLogStream() {
  if (logEs) { logEs.close(); logEs = null; }
}

logToggleBtn.addEventListener('click', () => {
  const visible = logPanel.style.display !== 'none';
  if (visible) {
    logPanel.style.display = 'none';
    stopLogStream();
  } else {
    logPanel.style.display = '';
    startLogStream();
  }
});

if (logCloseBtn) {
  logCloseBtn.addEventListener('click', () => {
    logPanel.style.display = 'none';
    stopLogStream();
  });
}

if (logClearBtn) {
  logClearBtn.addEventListener('click', () => {
    logBody.innerHTML = '';
  });
}

// auto-scroll toggle on manual scroll
if (logBody) {
  logBody.addEventListener('scroll', () => {
    const atBottom = logBody.scrollHeight - logBody.scrollTop - logBody.clientHeight < 30;
    logAutoScroll = atBottom;
  });
}

// Server shutdown button
if (shutdownBtn) {
  shutdownBtn.addEventListener('click', async () => {
    if (!confirm('Stop the server? You will need to restart it manually.')) return;
    shutdownBtn.disabled = true;
    try {
      await fetch('/api/server/shutdown', { method: 'POST' });
      appendLogLine('[UI] Shutdown requested. Server stopping...', 'WARNING');
      if (logPanel.style.display === 'none') {
        logPanel.style.display = '';
        startLogStream();
      }
    } catch (e) {
      appendLogLine('[UI] Shutdown request failed: ' + e.message, 'ERROR');
      shutdownBtn.disabled = false;
    }
  });
}

