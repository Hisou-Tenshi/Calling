const $ = (sel) => document.querySelector(sel);

const messagesEl = $("#messages");
const chatForm = $("#chatForm");
const promptEl = $("#prompt");
const sendBtn = $("#sendBtn");
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

function setStatus(text) {
  statusEl.textContent = text || "";
}

function isCurrentConversationEmpty() {
  return (messages || []).length === 0 && (uploadedFiles || []).length === 0;
}

function renderMessages() {
  messagesEl.innerHTML = "";
  for (const m of messages) {
    const div = document.createElement("div");
    div.className = `msg ${m.role}`;
    const meta = document.createElement("div");
    meta.className = "msg-meta";
    if (m.role === "user") {
      meta.textContent = "You";
    } else {
      meta.textContent = (m.model || "").trim() ? m.model : "Model";
    }

    const content = document.createElement("div");
    content.className = "msg-content";
    content.textContent = m.content || "";

    div.appendChild(meta);
    div.appendChild(content);
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

async function sendMessage() {
  const model = getSelectedModel();
  if (!model) {
    setStatus("Please select or type a model id.");
    return;
  }
  await ensureConversationSelected();
  if (!conversationId) return;

  const rag_enabled = !!ragToggle.checked;
  const force_web_search = !!forceSearchToggle.checked;

  const body = {
    conversation_id: conversationId,
    model,
    messages: messages,
    rag_enabled,
    force_web_search,
    uploaded_files: uploadedFiles,
  };

  setStatus("Waiting for assistant...");
  sendBtn.disabled = true;
  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Chat failed");

    const ans = data.assistant || "";
    messages.push({ role: "assistant", content: ans, model });
    renderMessages();

    if (forceSearchToggle.checked && data.web_search_called) {
      setStatus("web_search used.");
    } else if (forceSearchToggle.checked && !data.web_search_called) {
      setStatus("web_search not detected (model may have answered anyway).");
    } else {
      setStatus("Done.");
    }

    await refreshConversationList();
  } catch (e) {
    setStatus(String(e?.message || e));
  } finally {
    sendBtn.disabled = false;
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

