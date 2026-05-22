// MOCHA chat UI

const state = {
  sessionId: null,
  sessions: [],
  selectedIds: new Set(),
  streaming: false,
  abortController: null,
};

const els = {
  sessionList: document.getElementById("session-list"),
  newBtn: document.getElementById("new-session"),
  bulkBar: document.getElementById("bulk-bar"),
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
  // Drop selections that no longer exist
  const existingIds = new Set(state.sessions.map((s) => s.id));
  for (const id of state.selectedIds) {
    if (!existingIds.has(id)) state.selectedIds.delete(id);
  }

  for (const s of state.sessions) {
    const item = document.createElement("div");
    item.className = "session-item" + (s.id === state.sessionId ? " active" : "");

    const check = document.createElement("input");
    check.type = "checkbox";
    check.className = "session-check";
    check.checked = state.selectedIds.has(s.id);
    check.title = "선택";
    check.onclick = (ev) => ev.stopPropagation();
    check.onchange = () => {
      if (check.checked) state.selectedIds.add(s.id);
      else state.selectedIds.delete(s.id);
      renderBulkBar();
    };
    item.appendChild(check);

    const title = document.createElement("span");
    title.className = "session-title";
    title.textContent = s.title;
    title.onclick = () => loadSession(s.id);
    item.appendChild(title);

    const del = document.createElement("button");
    del.className = "session-del";
    del.title = "이 분석 삭제";
    del.setAttribute("aria-label", "삭제");
    del.innerHTML = "&#x2715;";
    del.onclick = (ev) => {
      ev.stopPropagation();
      deleteSession(s.id, s.title);
    };
    item.appendChild(del);

    els.sessionList.appendChild(item);
  }
  renderBulkBar();
}

function renderBulkBar() {
  if (!els.bulkBar) return;
  const n = state.selectedIds.size;
  if (n === 0) {
    els.bulkBar.innerHTML = "";
    els.bulkBar.classList.remove("active");
    return;
  }
  els.bulkBar.classList.add("active");
  els.bulkBar.innerHTML = `
    <button class="bulk-action bulk-delete">🗑 선택 ${n}개 삭제</button>
    <button class="bulk-action bulk-cancel">취소</button>
  `;
  els.bulkBar.querySelector(".bulk-delete").onclick = () => deleteSelected();
  els.bulkBar.querySelector(".bulk-cancel").onclick = () => {
    state.selectedIds.clear();
    renderSessions();
  };
}

async function deleteSession(id, title) {
  if (!confirm(`"${title}" 분석을 삭제할까요? 메시지도 함께 삭제됩니다.`)) {
    return;
  }
  const r = await fetch(`/api/sessions/${id}`, { method: "DELETE" });
  if (!r.ok) {
    alert("삭제 실패: " + r.status);
    return;
  }
  state.selectedIds.delete(id);
  if (state.sessionId === id) {
    state.sessionId = null;
    clearMessages();
  }
  await fetchSessions();
}

async function deleteSelected() {
  const ids = Array.from(state.selectedIds);
  if (ids.length === 0) return;
  if (!confirm(`선택한 ${ids.length}개 분석을 삭제할까요? 메시지도 함께 삭제됩니다.`)) {
    return;
  }
  const results = await Promise.all(
    ids.map((id) =>
      fetch(`/api/sessions/${id}`, { method: "DELETE" }).then((r) => ({ id, ok: r.ok })),
    ),
  );
  const failed = results.filter((r) => !r.ok);
  if (failed.length > 0) {
    alert(`${failed.length}개 삭제 실패 (id: ${failed.map((r) => r.id).join(", ")})`);
  }
  // If active session was in the batch, clear chat
  if (ids.includes(state.sessionId)) {
    state.sessionId = null;
    clearMessages();
  }
  state.selectedIds.clear();
  await fetchSessions();
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

  // Per-image / per-table copy buttons (only meaningful when markdown rendered)
  if (rendered) {
    enhanceImages(content);
    enhanceTables(content);
  }

  inner.appendChild(avatar);
  inner.appendChild(content);
  row.appendChild(inner);
  els.messages.appendChild(row);
  scrollToBottom();
  return { row, content };
}

// Semantic labels — translate raw tool names → user-friendly progress
const TOOL_SEMANTIC = {
  Bash: "📊 분석 실행 중...",
  Read: "📋 자료 확인 중...",
  Write: "✍️ 결과 정리 중...",
  Edit: "✏️ 답변 수정 중...",
  Glob: "🔍 파일 탐색 중...",
  Grep: "🔍 자료 검색 중...",
  Skill: "🎨 sub-skill 호출 중...",
  Agent: "🤝 sub-agent 호출 중...",
  AskUserQuestion: "❓ 사용자 확인 중...",
};

function appendToolChip(name) {
  const label = TOOL_SEMANTIC[name] || `🔧 ${name}`;
  // Merge consecutive identical labels into a count badge
  const last = els.messages.lastElementChild;
  if (last && last.classList.contains("tool-chip") && last.dataset.toolName === name) {
    const count = parseInt(last.dataset.count || "1", 10) + 1;
    last.dataset.count = String(count);
    last.textContent = `${label} (${count})`;
    return;
  }
  const chip = document.createElement("div");
  chip.className = "tool-chip";
  chip.dataset.toolName = name;
  chip.dataset.count = "1";
  chip.textContent = label;
  els.messages.appendChild(chip);
  scrollToBottom();
}

const DOMAIN_LABEL = {
  ml_1m: "🎬 ML-1M",
  watcha_main: "🎞️ Watcha",
  adult: "🔞 성인+",
  pedia: "⭐ 피디아",
  unknown: "❔ 도메인 미정",
};

function appendGatewayChip(payload) {
  const chip = document.createElement("div");
  chip.className = "gateway-chip";
  if (payload.status === "classifying") {
    chip.textContent = "🚦 의도 분류 중...";
    chip.dataset.gatewayStatus = "classifying";
  } else if (payload.status === "classified") {
    const trackIcon = payload.track === "fast" ? "🏎️" : "🐢";
    const trackLabel = payload.track === "fast" ? "Fast" : "Slow";
    const domainLabel = DOMAIN_LABEL[payload.domain] || payload.domain || "";
    chip.textContent = `${trackIcon} ${trackLabel} · ${payload.intent}` +
      (domainLabel ? ` · ${domainLabel}` : "");
    chip.dataset.gatewayStatus = "classified";
    chip.dataset.track = payload.track;
    if (payload.domain) chip.dataset.domain = payload.domain;
    // Replace prior "classifying" chip if present
    const prev = els.messages.querySelector('.gateway-chip[data-gateway-status="classifying"]');
    if (prev) {
      prev.replaceWith(chip);
      scrollToBottom();
      return;
    }
  }
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
  state.abortController = new AbortController();
  setSendButtonMode("stop");

  appendMessage("user", text, { rendered: true });
  const { content: botContent } = appendMessage("assistant", "", { rendered: false });
  botContent.classList.add("streaming");
  let buf = "";
  let aborted = false;

  try {
    const resp = await fetch(`/api/sessions/${state.sessionId}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text }),
      signal: state.abortController.signal,
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
    if (err.name === "AbortError") {
      aborted = true;
      buf += (buf ? "\n\n" : "") + "_⏹ 중지됨_";
    } else {
      appendError(`오류: ${err.message}`);
    }
  } finally {
    botContent.classList.remove("streaming");
    botContent.dataset.raw = buf;
    botContent.innerHTML = renderMarkdown(buf);
    // re-attach actions (overwritten by innerHTML)
    reattachActions(botContent);
    state.streaming = false;
    state.abortController = null;
    setSendButtonMode("send");
    fetchSessions();
  }
}

function setSendButtonMode(mode) {
  // mode: "send" (default arrow) or "stop" (square — interrupt streaming)
  els.send.disabled = false;
  if (mode === "stop") {
    els.send.dataset.mode = "stop";
    els.send.setAttribute("aria-label", "중지");
    els.send.innerHTML =
      '<svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor">' +
      '<rect x="5" y="5" width="14" height="14" rx="1.5"/></svg>';
  } else {
    els.send.dataset.mode = "send";
    els.send.setAttribute("aria-label", "전송");
    els.send.innerHTML =
      '<svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor">' +
      '<path d="M3 11l18-8-8 18-2-8z"/></svg>';
  }
}

function abortCurrentStream() {
  if (state.streaming && state.abortController) {
    state.abortController.abort();
  }
}

function reattachActions(content) {
  // Message-level "copy whole message" action
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

  // Per-image / per-table copy buttons
  enhanceImages(content);
  enhanceTables(content);
}

// ---------- image / table copy enhancers ----------

function enhanceImages(content) {
  content.querySelectorAll("img").forEach((img) => {
    if (img.dataset.enhanced) return;
    img.dataset.enhanced = "1";
    const wrap = document.createElement("div");
    wrap.className = "img-wrap";
    img.parentNode.insertBefore(wrap, img);
    wrap.appendChild(img);

    const btn = document.createElement("button");
    btn.className = "media-copy-btn";
    btn.textContent = "🖼 이미지 복사";
    btn.onclick = () => copyImageToClipboard(img, btn);
    wrap.appendChild(btn);

    // Re-anchor to bottom when the chart finishes loading — otherwise the
    // sudden height bump pushes the composer below the fold.
    if (!img.complete) {
      img.addEventListener("load", scrollToBottom, { once: true });
    }
  });
}

function enhanceTables(content) {
  content.querySelectorAll("table").forEach((table) => {
    if (table.dataset.enhanced) return;
    table.dataset.enhanced = "1";
    const wrap = document.createElement("div");
    wrap.className = "table-wrap";
    table.parentNode.insertBefore(wrap, table);
    wrap.appendChild(table);

    const btn = document.createElement("button");
    btn.className = "media-copy-btn";
    btn.textContent = "📋 표 복사 (MD)";
    btn.onclick = () => copyTableAsMd(table, btn);
    wrap.appendChild(btn);
  });
}

async function copyImageToClipboard(img, btn) {
  const original = btn.textContent;
  try {
    // Image lives at same-origin (/eda-files/...) so canvas isn't tainted.
    const canvas = document.createElement("canvas");
    canvas.width = img.naturalWidth || img.width;
    canvas.height = img.naturalHeight || img.height;
    canvas.getContext("2d").drawImage(img, 0, 0);
    const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/png"));
    await navigator.clipboard.write([new ClipboardItem({ "image/png": blob })]);
    btn.textContent = "✓ 복사됨";
  } catch (err) {
    btn.textContent = "✗ 실패";
    console.error("image copy failed:", err);
  }
  setTimeout(() => (btn.textContent = original), 1500);
}

function tableToMarkdown(table) {
  const rows = Array.from(table.querySelectorAll("tr"));
  if (rows.length === 0) return "";
  return rows
    .map((row, i) => {
      const cells = Array.from(row.querySelectorAll("th, td")).map((c) =>
        c.textContent.trim().replace(/\|/g, "\\|").replace(/\n/g, " "),
      );
      const line = "| " + cells.join(" | ") + " |";
      if (i === 0) {
        return line + "\n|" + cells.map(() => " --- ").join("|") + "|";
      }
      return line;
    })
    .join("\n");
}

async function copyTableAsMd(table, btn) {
  const original = btn.textContent;
  try {
    await navigator.clipboard.writeText(tableToMarkdown(table));
    btn.textContent = "✓ 복사됨";
  } catch (err) {
    btn.textContent = "✗ 실패";
    console.error("table copy failed:", err);
  }
  setTimeout(() => (btn.textContent = original), 1500);
}

function handleEvent(ev, botContent, appendToBuf) {
  if (ev.type === "text") {
    appendToBuf(ev.text);
    botContent.dataset.raw = (botContent.dataset.raw || "") + ev.text;
    botContent.textContent = botContent.dataset.raw;
    scrollToBottom();
  } else if (ev.type === "tool") {
    appendToolChip(ev.name);
  } else if (ev.type === "gateway") {
    appendGatewayChip(ev);
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
  // Send button doubles as stop while streaming.
  if (state.streaming) {
    abortCurrentStream();
    return;
  }
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

// ESC anywhere on the page interrupts an in-flight stream.
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && state.streaming) {
    e.preventDefault();
    abortCurrentStream();
  }
});

document.addEventListener("click", (e) => {
  if (e.target.classList?.contains("example")) {
    sendMessage(e.target.textContent);
  }
});

fetchSessions();
