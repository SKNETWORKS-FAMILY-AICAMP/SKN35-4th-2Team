// 채팅 화면의 동작. 서버와는 아래 "약속"(주소와 형식)으로만 대화한다. 서버가 답을 어떻게 만드는지는 모른다.
//   POST /api/auth/signup/, /api/auth/login/  {"username", "password"}  → {"user": {...}} 또는 {"error": "..."}
//   POST /api/auth/logout/ , GET /api/auth/me/ → {"user": {...} 또는 null}
//   GET  /api/conversations/                → {"conversations": [{"id", "title", "updated_at"}]}
//   GET  /api/conversations/<id>/           → {"id", "title", "messages": [{"role", "content", "sources"}]}
//   DELETE /api/conversations/<id>/
//   POST /api/chat/  {"question": "...", "conversation_id": 12 (이어서 질문할 때만)}
//     응답은 stage(처리 단계) / token(답변 조각) / sources(출처) / done(전체 답변) / error(오류 문장) 이벤트
// 답변은 renderMarkdown(markdown.js)으로 그리고, 서버가 준 글은 모두 textContent로만 넣는다(HTML로 실행되지 않게).

const authEl = document.getElementById("auth");
const appEl = document.getElementById("app");
const messagesEl = document.getElementById("messages");
const statusEl = document.getElementById("status");
const form = document.getElementById("chat-form");
const input = document.getElementById("question");
const sendButton = document.getElementById("send");
const listEl = document.getElementById("conversations");
const userNameEl = document.getElementById("user-name");
const welcomeTemplate = document.getElementById("welcome").cloneNode(true);

let conversationId = null; // 지금 열려 있는 대화 (null이면 새 대화)
let busy = false; // 답변을 받는 중에는 대화를 바꾸거나 지우지 못하게 한다

// ---------------------------------------------------------------- 공통
function csrfToken() {
  const match = document.cookie.match(/(?:^|; )csrftoken=([^;]*)/);
  return match ? decodeURIComponent(match[1]) : "";
}

async function api(url, { method = "GET", body } = {}) {
  const options = { method, headers: { "X-CSRFToken": csrfToken() } };
  if (body !== undefined) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  const response = await fetch(url, options);
  let data = {};
  try { data = await response.json(); } catch (error) { /* 본문이 없거나 JSON이 아니면 빈 값 */ }
  if (!response.ok && !data.error) data.error = `서버 오류(${response.status})가 발생했습니다. 잠시 후 다시 시도하고, 계속되면 팀에 알려 주세요.`;
  return { ok: response.ok, status: response.status, data };
}

function scrollToEnd() {
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function isSafeUrl(value) {
  try {
    const url = new URL(value);
    return url.protocol === "https:" || url.protocol === "http:";
  } catch (error) {
    return false;
  }
}

// ---------------------------------------------------------------- 로그인, 가입
const authForm = document.getElementById("auth-form");
const authError = document.getElementById("auth-error");
const authSubmit = document.getElementById("auth-submit");
const authRules = document.getElementById("auth-rules");
const authUsername = document.getElementById("auth-username");
const authPassword = document.getElementById("auth-password");
const tabLogin = document.getElementById("tab-login");
const tabSignup = document.getElementById("tab-signup");
let authMode = "login";

function setAuthMode(mode) {
  authMode = mode;
  tabLogin.setAttribute("aria-selected", String(mode === "login"));
  tabSignup.setAttribute("aria-selected", String(mode === "signup"));
  authSubmit.textContent = mode === "login" ? "로그인" : "가입하고 시작하기";
  authRules.hidden = mode !== "signup";
  authPassword.autocomplete = mode === "login" ? "current-password" : "new-password";
  showAuthError("");
}

function showAuthError(message) {
  authError.textContent = message;
  authError.hidden = !message;
}

function showAuth(message = "") {
  appEl.hidden = true;
  authEl.hidden = false;
  showAuthError(message);
}

function showApp(user) {
  authEl.hidden = true;
  appEl.hidden = false;
  userNameEl.textContent = user.username;
  authPassword.value = "";
  newChat();
  loadConversations();
  input.focus();
}

tabLogin.addEventListener("click", () => setAuthMode("login"));
tabSignup.addEventListener("click", () => setAuthMode("signup"));

authForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  authSubmit.disabled = true;
  showAuthError("");
  try {
    const { ok, data } = await api(`/api/auth/${authMode}/`, { method: "POST", body: { username: authUsername.value, password: authPassword.value } });
    if (ok) showApp(data.user);
    else showAuthError(data.error || "요청을 처리하지 못했습니다.");
  } catch (error) {
    showAuthError("서버에 연결하지 못했습니다. 인터넷 연결을 확인해 주세요.");
  } finally {
    authSubmit.disabled = false;
  }
});

document.getElementById("logout").addEventListener("click", async () => {
  if (busy) return;
  try { await api("/api/auth/logout/", { method: "POST" }); } catch (error) { /* 서버에 닿지 않아도 화면은 로그아웃 상태로 */ }
  authPassword.value = "";
  showAuth();
});

// ---------------------------------------------------------------- 말풍선
function addBubble(role, text) {
  const welcome = document.getElementById("welcome");
  if (welcome) welcome.remove();
  const bubble = document.createElement("div");
  bubble.className = `bubble ${role}`;
  if (role === "assistant") bubble.replaceChildren(renderMarkdown(text));
  else bubble.textContent = text;
  messagesEl.appendChild(bubble);
  scrollToEnd();
  return bubble;
}

function showSources(sources) {
  const usable = (sources || []).filter((source) => source && isSafeUrl(source.url));
  if (!usable.length) return;
  const box = document.createElement("div");
  box.className = "sources";
  const title = document.createElement("h2");
  title.textContent = "참고한 출처";
  const list = document.createElement("ol");
  usable.forEach((source) => {
    const item = document.createElement("li");
    const link = document.createElement("a");
    link.href = source.url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.textContent = source.title || source.url;
    item.appendChild(link);
    list.appendChild(item);
  });
  box.append(title, list);
  messagesEl.appendChild(box);
  scrollToEnd();
}

// ---------------------------------------------------------------- 대화 목록
function renderConversationList(items) {
  listEl.replaceChildren();
  if (!items.length) {
    const empty = document.createElement("p");
    empty.className = "empty-list";
    empty.textContent = "아직 대화가 없습니다.";
    listEl.append(empty);
    return;
  }
  items.forEach((item) => {
    const row = document.createElement("div");
    row.className = "conversation" + (item.id === conversationId ? " current" : "");
    const open = document.createElement("button");
    open.type = "button";
    open.className = "open";
    open.textContent = item.title || "새 대화";
    open.title = item.title || "새 대화";
    open.addEventListener("click", () => openConversation(item.id));
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "remove";
    remove.textContent = "✕";
    remove.setAttribute("aria-label", "이 대화 삭제");
    remove.addEventListener("click", () => removeConversation(item));
    const actions = document.createElement("details");
    actions.className = "conversation-actions";
    const toggle = document.createElement("summary");
    toggle.textContent = "⋯";
    toggle.setAttribute("aria-label", `${item.title || "새 대화"} 메뉴`);
    const rename = document.createElement("button");
    rename.type = "button";
    rename.textContent = "이름 변경";
    actions.append(toggle, rename);
    actions.addEventListener("click", (event) => event.stopPropagation());
    actions.addEventListener("keydown", (event) => {
      if (event.key === "Escape") { actions.open = false; toggle.focus(); }
    });
    rename.addEventListener("click", () => {
      actions.open = false;
      editConversationTitle(item, open, toggle);
    });
    row.append(open, actions, remove);
    listEl.append(row);
  });
}

// Native modal supplies focus trapping, keyboard access and Escape cancellation.
function editConversationTitle(item, titleButton, menuButton) {
  if (document.querySelector(".rename-dialog")) return;
  const dialog = document.createElement("dialog");
  dialog.className = "rename-dialog";
  dialog.setAttribute("aria-labelledby", "rename-heading");
  const editor = document.createElement("form");
  editor.noValidate = true;
  const heading = document.createElement("h2");
  heading.id = "rename-heading";
  heading.textContent = "대화 이름 변경";
  const label = document.createElement("label");
  label.htmlFor = "rename-title";
  label.textContent = "제목 (1~100자)";
  const field = document.createElement("input");
  field.id = "rename-title";
  field.name = "title";
  field.value = item.title || "새 대화";
  field.setAttribute("aria-describedby", "rename-error");
  const notice = document.createElement("p");
  notice.id = "rename-error";
  notice.className = "rename-error";
  notice.setAttribute("role", "alert");
  const controls = document.createElement("div");
  controls.className = "rename-controls";
  const cancel = document.createElement("button");
  cancel.type = "button";
  cancel.textContent = "취소";
  const save = document.createElement("button");
  save.type = "submit";
  save.textContent = "저장";
  let saving = false;
  const close = () => { if (!saving) dialog.close(); };
  cancel.addEventListener("click", close);
  dialog.addEventListener("cancel", (event) => {
    if (saving) event.preventDefault();
  });
  dialog.addEventListener("close", () => {
    dialog.remove();
    if (menuButton.isConnected) menuButton.focus();
  });
  editor.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (saving) return;
    const title = field.value.trim();
    if (!title || Array.from(title).length > 100) {
      notice.textContent = title ? "제목은 100자 이하로 입력해 주세요." : "제목을 입력해 주세요.";
      field.setAttribute("aria-invalid", "true");
      field.focus();
      return;
    }
    saving = true;
    save.disabled = cancel.disabled = field.disabled = true;
    notice.textContent = "";
    field.removeAttribute("aria-invalid");
    try {
      const { ok, data } = await api(`/api/conversations/${item.id}/`, { method: "PATCH", body: { title } });
      if (!ok) throw new Error(data.error || "제목을 저장하지 못했습니다. 다시 시도해 주세요.");
      item.title = data.title;
      // Text-only rendering; keep row position and the open conversation unchanged.
      titleButton.textContent = data.title;
      titleButton.title = data.title;
      menuButton.setAttribute("aria-label", `${data.title} 메뉴`);
      dialog.close();
    } catch (error) {
      notice.textContent = `${error.message || "저장에 실패했습니다."} 제목을 확인하고 다시 저장해 주세요.`;
    } finally {
      saving = false;
      save.disabled = cancel.disabled = field.disabled = false;
      if (dialog.open) field.focus();
    }
  });
  controls.append(cancel, save);
  editor.append(heading, label, field, notice, controls);
  dialog.append(editor);
  document.body.append(dialog);
  dialog.showModal();
  field.focus();
  field.select();
}

async function loadConversations() {
  try {
    const { ok, status, data } = await api("/api/conversations/");
    if (status === 401) return showAuth("로그인이 필요합니다.");
    if (ok) renderConversationList(data.conversations || []);
  } catch (error) { /* 목록을 못 불러와도 질문은 계속할 수 있다 */ }
}

function newChat() {
  if (busy) return;
  conversationId = null;
  messagesEl.replaceChildren(welcomeTemplate.cloneNode(true));
  statusEl.textContent = "";
  loadConversations();
}

async function openConversation(id) {
  if (busy || id === conversationId) return;
  try {
    const { ok, status, data } = await api(`/api/conversations/${id}/`);
    if (status === 401) return showAuth("로그인이 필요합니다.");
    if (!ok) { statusEl.textContent = data.error || "대화를 불러오지 못했습니다."; return; }
    conversationId = data.id;
    messagesEl.replaceChildren();
    data.messages.forEach((message) => {
      addBubble(message.role === "user" ? "user" : "assistant", message.content);
      if (message.role !== "user") showSources(message.sources);
    });
    statusEl.textContent = "";
    scrollToEnd();
    loadConversations();
  } catch (error) {
    statusEl.textContent = "대화를 불러오지 못했습니다. 인터넷 연결을 확인해 주세요.";
  }
}

async function removeConversation(item) {
  if (busy) return;
  if (!window.confirm(`"${item.title || "새 대화"}" 대화를 삭제할까요? 되돌릴 수 없습니다.`)) return;
  try {
    const { ok, status, data } = await api(`/api/conversations/${item.id}/`, { method: "DELETE" });
    if (status === 401) return showAuth("로그인이 필요합니다.");
    if (!ok) { statusEl.textContent = data.error || "대화를 삭제하지 못했습니다."; return; }
    if (item.id === conversationId) newChat();
    else loadConversations();
  } catch (error) {
    statusEl.textContent = "대화를 삭제하지 못했습니다. 인터넷 연결을 확인해 주세요.";
  }
}

document.getElementById("new-chat").addEventListener("click", newChat);

// ---------------------------------------------------------------- 서버가 보내는 이벤트 읽기
// 이벤트 한 건("event: 이름\ndata: JSON\n\n")을 읽는다
function parseEvent(raw) {
  let name = "message";
  let data = "";
  raw.split("\n").forEach((line) => {
    if (line.startsWith("event:")) name = line.slice(6).trim();
    else if (line.startsWith("data:")) data += line.slice(5).trim();
  });
  try {
    return { name, data: JSON.parse(data) };
  } catch (error) {
    return { name, data };
  }
}

async function ask(question) {
  addBubble("user", question);
  const answerBubble = addBubble("assistant", "");
  let answer = "";
  let failed = false;
  let renderQueued = false;
  statusEl.textContent = "질문을 보내는 중…";

  // 조각이 올 때마다 마크다운을 다시 그리되, 화면 갱신 한 번에 한 번만 그린다
  const redraw = () => {
    renderQueued = false;
    if (failed) return; // 오류 문구를 조각 그리기가 덮어쓰지 않게 한다
    answerBubble.replaceChildren(renderMarkdown(answer));
    scrollToEnd();
  };

  const body = { question };
  if (conversationId !== null) body.conversation_id = conversationId;
  const response = await fetch("/api/chat/", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken() },
    body: JSON.stringify(body),
  });

  if (response.status === 401) {
    answerBubble.remove();
    showAuth("로그인이 필요합니다. 다시 로그인해 주세요.");
    return;
  }
  if (!response.ok || !response.body) {
    let message = "서버에서 답을 받지 못했습니다.";
    try { message = (await response.json()).error || message; } catch (error) { /* 본문이 JSON이 아니면 기본 문장 */ }
    answerBubble.textContent = message;
    answerBubble.classList.add("error");
    statusEl.textContent = "";
    return;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let boundary;
    while ((boundary = buffer.indexOf("\n\n")) !== -1) {
      const { name, data } = parseEvent(buffer.slice(0, boundary));
      buffer = buffer.slice(boundary + 2);
      if (name === "stage") {
        statusEl.textContent = data;
      } else if (name === "token") {
        answer += data;
        if (!renderQueued) { renderQueued = true; requestAnimationFrame(redraw); }
      } else if (name === "sources") {
        showSources(data);
      } else if (name === "done") {
        answer = data.answer || answer; // 조각이 모자라도 전체 답변으로 맞춘다
        redraw();
        if (data.conversation_id) conversationId = data.conversation_id;
      } else if (name === "error") {
        failed = true;
        answerBubble.textContent = data.message || "오류가 발생했습니다.";
        answerBubble.classList.add("error");
        if (data.conversation_id) conversationId = data.conversation_id; // 질문은 저장됐으니 같은 대화에서 이어간다
      }
    }
  }

  statusEl.textContent = "";
  if (!failed && !answerBubble.classList.contains("error")) redraw();
  loadConversations(); // 새 대화가 생겼거나 제목이 바뀌었을 수 있다
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const question = input.value.trim();
  if (!question || busy) return;
  input.value = "";
  busy = true;
  sendButton.disabled = true;
  try {
    await ask(question);
  } catch (error) {
    statusEl.textContent = "";
    addBubble("assistant", "연결에 문제가 생겼습니다. 인터넷 연결을 확인하고 다시 시도해 주세요.").classList.add("error");
  } finally {
    busy = false;
    sendButton.disabled = false;
    input.focus();
  }
});

input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    form.requestSubmit();
  }
});

// ---------------------------------------------------------------- 시작: 이미 로그인한 상태인지 확인한다
(async function start() {
  setAuthMode("login");
  try {
    const { data } = await api("/api/auth/me/");
    if (data.user) showApp(data.user);
    else showAuth();
  } catch (error) {
    showAuth("서버에 연결하지 못했습니다. 잠시 후 새로고침해 주세요.");
  }
})();
