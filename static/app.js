// MOCHA chat UI

const state = {
  sessionId: null,
  sessions: [],
  streaming: false,
};

const els = {
  sessionList: document.getElementById("session-list"),
  newBtn: document.getElementById("new-session"),
  messages: document.getElementById("messages"),
  form: document.getElementById("chat-form"),
  prompt: document.getElementById("prompt"),
  send: document.getElementById("send-btn"),
};

// Markdown renderer setup
marked.setOptions({
  gfm: true,
  breaks: true,
  highlight(code, lang) {
    if (lang && hljs.getLanguage(lang)) {
      try {
        return hljs.highlight(code, { language: lang }).value;
      } catch {}
    }
    try {
      return hljs.highlightAuto(code).value;
    } catch {
      return code;
    }
  },
});

function renderMarkdown(text) {
  const raw = marked.parse(text || "");
  return DOMPurify.sanitize(raw);
}

function escapeHtml(s) {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

// ---------- session API ----------

async function fetchSessions() {
  const r = await fetch("/api/sessions");
  state.sessions = await r.json();
  renderSessions();
}

function renderSessions() {
  els.sessionList.innerHTML = "";
  for (const s of state.sessions) {
    const item = document.createElement("div");
    item.className = "session-item" + (s.id === state.sessionId ? " active" : "");
    item.textContent = s.title;
    item.onclick = () => loadSession(s.id);
    els.sessionList.appendChild(item);
  }
}

async function newSession(title = "새 분석") {
  const r = await fetch("/api/sessions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  });
  const s = await r.json();
  state.sessionId = s.id;
  await fetchSessions();
  clearMessages();
  return s;
}

async function loadSession(id) {
  state.sessionId = id;
  renderSessions();
  const r = await fetch(`/api/sessions/${id}/messages`);
  const msgs = await r.json();
  clearMessages();
  for (const m of msgs) {
    appendMessage(m.role, m.content, { rendered: true });
  }
}

function clearMessages() {
  els.messages.innerHTML = "";
}

// ---------- message rendering ----------

function appendMessage(role, text, { rendered = false } = {}) {
  const row = document.createElement("div");
  row.className = `msg-row ${role}`;

  const inner = document.createElement("div");
  inner.className = "msg-inner";

  const avatar = document.createElement("div");
  avatar.className = `avatar ${role}`;
  avatar.textContent = role === "assistant" ? "☕" : "나";

  const content = document.createElement("div");
  content.className = "msg-content";
  content.dataset.raw = text;
  if (rendered) {
    content.innerHTML = renderMarkdown(text);
  } else {
    content.textContent = text;
  }

  const actions = document.createElement("div");
  actions.className = "msg-actions";
  const copyBtn = document.createElement("button");
  copyBtn.className = "msg-action-btn";
  copyBtn.textContent = "📋 복사";
  copyBtn.onclick = async () => {
    await navigator.clipboard.writeText(content.dataset.raw || content.textContent);
    copyBtn.textContent = "✓ 복사됨";
    setTimeout(() => (copyBtn.textContent = "📋 복사"), 1200);
  };
  actions.appendChild(copyBtn);
  content.appendChild(actions);

  inner.appendChild(avatar);
  inner.appendChild(content);
  row.appendChild(inner);
  els.messages.appendChild(row);
  scrollToBottom();
  return { row, content };
}

function appendToolChip(name) {
  const chip = document.createElement("div");
  chip.className = "tool-chip";
  chip.textContent = `🔧 ${name}`;
  els.messages.appendChild(chip);
  scrollToBottom();
}

function appendError(msg) {
  const row = document.createElement("div");
  row.className = "msg-row error";
  const inner = document.createElement("div");
  inner.className = "msg-inner";
  const content = document.createElement("div");
  content.className = "msg-content";
  content.textContent = msg;
  inner.appendChild(content);
  row.appendChild(inner);
  els.messages.appendChild(row);
  scrollToBottom();
}

function scrollToBottom() {
  els.messages.scrollTop = els.messages.scrollHeight;
}

// ---------- chat send ----------

async function sendMessage(text) {
  if (!text.trim() || state.streaming) return;

  if (!state.sessionId) {
    const title = text.slice(0, 30) + (text.length > 30 ? "…" : "");
    await newSession(title);
  }

  // Remove welcome screen if present
  const welcome = els.messages.querySelector(".welcome");
  if (welcome) welcome.remove();

  state.streaming = true;
  els.send.disabled = true;

  appendMessage("user", text, { rendered: true });
  const { content: botContent } = appendMessage("assistant", "", { rendered: false });
  botContent.classList.add("streaming");
  let buf = "";

  try {
    const resp = await fetch(`/api/sessions/${state.sessionId}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text }),
    });

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let sseBuf = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      sseBuf += decoder.decode(value, { stream: true });
      const lines = sseBuf.split("\n\n");
      sseBuf = lines.pop() || "";
      for (const line of lines) {
        if (!line.startsWith("data: ")) continue;
        let payload;
        try {
          payload = JSON.parse(line.slice(6));
        } catch {
          continue;
        }
        handleEvent(payload, botContent, (text) => (buf += text));
      }
    }
  } catch (err) {
    appendError(`오류: ${err.message}`);
  } finally {
    botContent.classList.remove("streaming");
    botContent.dataset.raw = buf;
    botContent.innerHTML = renderMarkdown(buf);
    // re-attach actions (overwritten by innerHTML)
    reattachActions(botContent);
    state.streaming = false;
    els.send.disabled = false;
    fetchSessions();
  }
}

function reattachActions(content) {
  const actions = document.createElement("div");
  actions.className = "msg-actions";
  const copyBtn = document.createElement("button");
  copyBtn.className = "msg-action-btn";
  copyBtn.textContent = "📋 복사";
  copyBtn.onclick = async () => {
    await navigator.clipboard.writeText(content.dataset.raw);
    copyBtn.textContent = "✓ 복사됨";
    setTimeout(() => (copyBtn.textContent = "📋 복사"), 1200);
  };
  actions.appendChild(copyBtn);
  content.appendChild(actions);
}

function handleEvent(ev, botContent, appendToBuf) {
  if (ev.type === "text") {
    appendToBuf(ev.text);
    botContent.dataset.raw = (botContent.dataset.raw || "") + ev.text;
    botContent.textContent = botContent.dataset.raw;
    scrollToBottom();
  } else if (ev.type === "tool") {
    appendToolChip(ev.name);
  } else if (ev.type === "error") {
    appendError(ev.error);
  } else if (ev.type === "done") {
    // Final markdown render done in finally block
  } else if (ev.type === "rate_limit") {
    // ignore noisy info
  }
}

// ---------- input ----------

function autoResize() {
  els.prompt.style.height = "auto";
  els.prompt.style.height = Math.min(els.prompt.scrollHeight, 200) + "px";
}

els.newBtn.onclick = () => {
  state.sessionId = null;
  clearMessages();
  // Re-render welcome
  const div = document.createElement("div");
  div.className = "welcome";
  div.innerHTML = `
    <div class="welcome-logo">☕</div>
    <h2>MOCHA</h2>
    <p>자연어로 Watcha 데이터에 대해 물어보세요.</p>
    <div class="examples">
      <button class="example">graph_modeling 데이터 EDA 리포트 만들어줘</button>
      <button class="example">큰손 유저는 누구야?</button>
      <button class="example">장르 분석해줘</button>
      <button class="example">노션에 올려줘</button>
    </div>
  `;
  els.messages.appendChild(div);
  div.querySelectorAll(".example").forEach((b) => {
    b.onclick = () => sendMessage(b.textContent);
  });
  renderSessions();
};

els.form.onsubmit = (e) => {
  e.preventDefault();
  const text = els.prompt.value;
  els.prompt.value = "";
  autoResize();
  sendMessage(text);
};

els.prompt.addEventListener("input", autoResize);
els.prompt.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    els.form.requestSubmit();
  }
});

document.addEventListener("click", (e) => {
  if (e.target.classList?.contains("example")) {
    sendMessage(e.target.textContent);
  }
});

fetchSessions();
