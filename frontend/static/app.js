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

