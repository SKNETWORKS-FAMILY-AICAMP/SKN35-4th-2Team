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
  try {
    data = await response.json();
  } catch (error) {
    /* 본문이 없거나 JSON이 아니면 빈 값 */
  }
  if (!response.ok && !data.error)
    data.error = `서버 오류(${response.status})가 발생했습니다. 잠시 후 다시 시도하고, 계속되면 팀에 알려 주세요.`;
  return { ok: response.ok, status: response.status, data };
}

function scrollToEnd() {
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

// ---------------------------------------------------------------- 테마 (라이트/다크)
// 고른 값은 이 브라우저에만 저장한다. 고른 적이 없으면 시스템 설정을 따른다(CSS가 처리).
const THEME_KEY = "codeclue-theme";
const systemDark = window.matchMedia("(prefers-color-scheme: dark)");

function currentTheme() {
  return (
    document.documentElement.dataset.theme ||
    (systemDark.matches ? "dark" : "light")
  );
}

function updateThemeButtons() {
  const next = currentTheme() === "dark" ? "라이트" : "다크";
  document.querySelectorAll(".theme-toggle").forEach((button) => {
    button.setAttribute("aria-label", `${next} 모드로 바꾸기`);
    button.title = `${next} 모드`;
  });
}

document.querySelectorAll(".theme-toggle").forEach((button) =>
  button.addEventListener("click", () => {
    const theme = currentTheme() === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem(THEME_KEY, theme);
    } catch (error) {
      /* 저장이 막혀 있어도 이번 화면에는 적용된다 */
    }
    updateThemeButtons();
  }),
);
systemDark.addEventListener("change", updateThemeButtons);
updateThemeButtons();

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
const authHints = document.querySelectorAll(".signup-only");
const authTitle = document.querySelector(".auth-title");
const authSub = document.querySelector(".auth-sub");
const authUsername = document.getElementById("auth-username");
const authPassword = document.getElementById("auth-password");
const tabLogin = document.getElementById("tab-login");
const tabSignup = document.getElementById("tab-signup");
let authMode = "login";

function setAuthMode(mode) {
  // 로그인 ↔ 가입으로 바꾸면 적던 값을 비운다 (같은 탭을 다시 누르면 그대로 둔다)
  if (mode !== authMode) {
    authUsername.value = "";
    authPassword.value = "";
  }
  authMode = mode;
  tabLogin.setAttribute("aria-selected", String(mode === "login"));
  tabSignup.setAttribute("aria-selected", String(mode === "signup"));
  authSubmit.textContent = mode === "login" ? "로그인" : "가입하고 시작하기";
  authTitle.textContent =
    mode === "login" ? "다시 오신 걸 환영해요" : "CodeClue 시작하기";
  authSub.textContent =
    mode === "login"
      ? "계정으로 로그인하고 대화를 이어가세요."
      : "아이디와 비밀번호만 있으면 바로 시작할 수 있어요.";
  authHints.forEach((hint) => {
    hint.hidden = mode !== "signup";
  });
  authPassword.autocomplete =
    mode === "login" ? "current-password" : "new-password";
  showAuthError("");
}

function showAuthError(message) {
  authError.textContent = message;
  authError.hidden = !message;
  if (!message)
    [authUsername, authPassword].forEach((field) =>
      field.removeAttribute("aria-invalid"),
    );
}

// 빈 칸이면 브라우저 기본 풍선 대신 화면 안에 알려 준다 (형식 검사는 서버가 한다)
function checkAuthFields() {
  const empty = [
    [authUsername, "아이디"],
    [authPassword, "비밀번호"],
  ].filter(([field]) => !field.value.trim());
  if (!empty.length) return true;
  empty.forEach(([field]) => field.setAttribute("aria-invalid", "true"));
  showAuthError(
    `${empty.map(([, name]) => name).join("와 ")}를 입력해 주세요.`,
  );
  empty[0][0].focus();
  return false;
}

[authUsername, authPassword].forEach((field) =>
  field.addEventListener("input", () => field.removeAttribute("aria-invalid")),
);

function showAuth(message = "") {
  closeNav();
  appEl.hidden = true;
  authEl.hidden = false;
  showAuthError(message);
}

function showApp(user) {
  authEl.hidden = true;
  appEl.hidden = false;
  userNameEl.textContent = user.username;
  document.getElementById("user-avatar").textContent = (
    user.username || "?"
  ).charAt(0);
  authPassword.value = "";
  newChat();
  loadConversations();
  input.focus();
}

tabLogin.addEventListener("click", () => setAuthMode("login"));
tabSignup.addEventListener("click", () => setAuthMode("signup"));

authForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  showAuthError("");
  if (!checkAuthFields()) return;
  authSubmit.disabled = true;
  try {
    const { ok, data } = await api(`/api/auth/${authMode}/`, {
      method: "POST",
      body: { username: authUsername.value, password: authPassword.value },
    });
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
  try {
    await api("/api/auth/logout/", { method: "POST" });
  } catch (error) {
    /* 서버에 닿지 않아도 화면은 로그아웃 상태로 */
  }
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

// 답변 첫 조각이 오기 전까지 말풍선 안에 보여 주는 "점 세 개 + 지금 하는 일"
function showTyping(bubble, label) {
  const box = document.createElement("div");
  box.className = "typing";
  const dots = document.createElement("span");
  dots.className = "dots";
  dots.setAttribute("aria-hidden", "true");
  dots.append(
    document.createElement("span"),
    document.createElement("span"),
    document.createElement("span"),
  );
  const text = document.createElement("span");
  text.className = "typing-label";
  text.textContent = label;
  box.append(dots, text);
  bubble.replaceChildren(box);
  bubble.setAttribute("aria-busy", "true");
  scrollToEnd();
}

function setTypingLabel(bubble, label) {
  const text = bubble.querySelector(".typing-label");
  if (text) text.textContent = label;
}

// 코드 블록의 복사 버튼 (말풍선은 답변 조각마다 다시 그려지므로 한 곳에서 받는다)
messagesEl.addEventListener("click", async (event) => {
  const button = event.target.closest(".copy-code");
  if (!button) return;
  const code = button.closest("pre")?.querySelector("code");
  if (!code) return;
  try {
    await navigator.clipboard.writeText(code.textContent);
    button.textContent = "복사됨";
  } catch (error) {
    button.textContent = "복사 실패";
  }
  setTimeout(() => {
    button.textContent = "복사";
  }, 1500);
});

function showSources(sources) {
  const usable = (sources || []).filter(
    (source) => source && isSafeUrl(source.url),
  );
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

// ---------------------------------------------------------------- 좁은 화면의 대화 목록 서랍
const menuButton = document.getElementById("menu-button");
const sidebarEl = document.getElementById("sidebar");
const narrowScreen = window.matchMedia("(max-width: 760px)");

function setNavOpen(open) {
  appEl.classList.toggle("nav-open", open);
  menuButton.setAttribute("aria-expanded", String(open));
  menuButton.setAttribute(
    "aria-label",
    open ? "대화 목록 닫기" : "대화 목록 열기",
  );
  sidebarEl.inert = narrowScreen.matches && !open; // 닫힌 서랍 안의 버튼에 Tab으로 들어가지 않게
  if (open) document.getElementById("new-chat").focus();
}

function closeNav() {
  if (appEl.classList.contains("nav-open")) setNavOpen(false);
}

menuButton.addEventListener("click", () =>
  setNavOpen(!appEl.classList.contains("nav-open")),
);
document.getElementById("backdrop").addEventListener("click", closeNav);
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && appEl.classList.contains("nav-open")) {
    closeNav();
    menuButton.focus();
  }
});
narrowScreen.addEventListener("change", () => setNavOpen(false)); // 화면 폭이 바뀌면 서랍을 닫힌 상태로 맞춘다
setNavOpen(false);

// ---------------------------------------------------------------- 알림(토스트)과 확인 창
// 브라우저 기본 alert/confirm 대신 화면 테마에 맞춘 것을 쓴다. 글은 모두 textContent로만 넣는다.
function iconSvg(name) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("aria-hidden", "true");
  const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
  use.setAttribute("href", `#i-${name}`);
  svg.append(use);
  return svg;
}

// type: "success" 또는 "error". 몇 초 뒤 저절로 사라지고, 누르면 바로 닫힌다.
function showToast(message, type = "success") {
  let stack = document.getElementById("toasts");
  if (!stack) {
    stack = document.createElement("div");
    stack.id = "toasts";
    stack.className = "toasts";
    stack.setAttribute("role", "status");
    stack.setAttribute("aria-live", "polite");
    document.body.append(stack);
  }
  const toast = document.createElement("div");
  toast.className = `toast toast-${type}`;
  const icon = document.createElement("span");
  icon.className = "toast-icon";
  icon.append(iconSvg(type === "error" ? "alert" : "check"));
  const text = document.createElement("span");
  text.textContent = message;
  toast.append(icon, text);
  stack.append(toast);
  const dismiss = () => {
    if (toast.classList.contains("leaving")) return;
    toast.classList.add("leaving");
    setTimeout(() => toast.remove(), 200);
  };
  toast.addEventListener("click", dismiss);
  setTimeout(dismiss, type === "error" ? 4500 : 2800);
}

// 확인 창. 확인을 누르면 true, 취소·Esc·바깥 누르기면 false로 끝나는 Promise를 돌려준다.
function confirmDialog({
  title,
  message,
  confirmText = "확인",
  danger = false,
}) {
  return new Promise((resolve) => {
    const dialog = document.createElement("dialog");
    dialog.className = "rename-dialog confirm-dialog";
    dialog.setAttribute("aria-labelledby", "confirm-heading");
    dialog.setAttribute("aria-describedby", "confirm-message");
    const badge = document.createElement("span");
    badge.className = `confirm-badge${danger ? " danger" : ""}`;
    badge.append(iconSvg(danger ? "trash" : "alert"));
    const heading = document.createElement("h2");
    heading.id = "confirm-heading";
    heading.textContent = title;
    const body = document.createElement("p");
    body.id = "confirm-message";
    body.className = "confirm-message";
    body.textContent = message;
    const controls = document.createElement("div");
    controls.className = "rename-controls";
    const cancel = document.createElement("button");
    cancel.type = "button";
    cancel.textContent = "취소";
    const ok = document.createElement("button");
    ok.type = "button";
    ok.className = danger ? "btn-danger" : "btn-confirm";
    ok.textContent = confirmText;
    controls.append(cancel, ok);
    dialog.append(badge, heading, body, controls);

    let answer = false;
    cancel.addEventListener("click", () => dialog.close());
    ok.addEventListener("click", () => {
      answer = true;
      dialog.close();
    });
    dialog.addEventListener("click", (event) => {
      // 창 바깥(어두운 배경)을 누르면 취소
      const box = dialog.getBoundingClientRect();
      const inside =
        event.clientX >= box.left &&
        event.clientX <= box.right &&
        event.clientY >= box.top &&
        event.clientY <= box.bottom;
      if (event.target === dialog && !inside) dialog.close();
    });
    dialog.addEventListener("close", () => {
      dialog.remove();
      resolve(answer);
    });
    document.body.append(dialog);
    dialog.showModal();
    cancel.focus(); // 되돌릴 수 없는 작업이라 기본 선택은 취소
  });
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
    row.className =
      "conversation" + (item.id === conversationId ? " current" : "");
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
      if (event.key === "Escape") {
        actions.open = false;
        toggle.focus();
      }
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
  const close = () => {
    if (!saving) dialog.close();
  };
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
      notice.textContent = title
        ? "제목은 100자 이하로 입력해 주세요."
        : "제목을 입력해 주세요.";
      field.setAttribute("aria-invalid", "true");
      field.focus();
      return;
    }
    saving = true;
    save.disabled = cancel.disabled = field.disabled = true;
    notice.textContent = "";
    field.removeAttribute("aria-invalid");
    try {
      const { ok, data } = await api(`/api/conversations/${item.id}/`, {
        method: "PATCH",
        body: { title },
      });
      if (!ok)
        throw new Error(
          data.error || "제목을 저장하지 못했습니다. 다시 시도해 주세요.",
        );
      item.title = data.title;
      // Text-only rendering; keep row position and the open conversation unchanged.
      titleButton.textContent = data.title;
      titleButton.title = data.title;
      menuButton.setAttribute("aria-label", `${data.title} 메뉴`);
      dialog.close();
      showToast("대화 이름을 변경했어요.");
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
  } catch (error) {
    /* 목록을 못 불러와도 질문은 계속할 수 있다 */
  }
}

function newChat() {
  if (busy) return;
  closeNav();
  conversationId = null;
  messagesEl.replaceChildren(welcomeTemplate.cloneNode(true));
  statusEl.textContent = "";
  loadConversations();
}

async function openConversation(id) {
  if (busy) return;
  closeNav();
  if (id === conversationId) return;
  try {
    const { ok, status, data } = await api(`/api/conversations/${id}/`);
    if (status === 401) return showAuth("로그인이 필요합니다.");
    if (!ok) {
      statusEl.textContent = data.error || "대화를 불러오지 못했습니다.";
      return;
    }
    conversationId = data.id;
    messagesEl.replaceChildren();
    data.messages.forEach((message) => {
      addBubble(
        message.role === "user" ? "user" : "assistant",
        message.content,
      );
      if (message.role !== "user") showSources(message.sources);
    });
    statusEl.textContent = "";
    scrollToEnd();
    loadConversations();
  } catch (error) {
    statusEl.textContent =
      "대화를 불러오지 못했습니다. 인터넷 연결을 확인해 주세요.";
  }
}

async function removeConversation(item) {
  if (busy) return;
  const confirmed = await confirmDialog({
    title: "대화를 삭제할까요?",
    message: `"${item.title || "새 대화"}" 대화와 그 안의 질문·답변이 모두 지워집니다. 삭제한 대화는 되돌릴 수 없어요.`,
    confirmText: "삭제",
    danger: true,
  });
  if (!confirmed || busy) return;
  try {
    const { ok, status, data } = await api(`/api/conversations/${item.id}/`, {
      method: "DELETE",
    });
    if (status === 401) return showAuth("로그인이 필요합니다.");
    if (!ok) {
      showToast(data.error || "대화를 삭제하지 못했습니다.", "error");
      return;
    }
    if (item.id === conversationId) newChat();
    else loadConversations();
    showToast("대화를 삭제했어요.");
  } catch (error) {
    showToast(
      "대화를 삭제하지 못했습니다. 인터넷 연결을 확인해 주세요.",
      "error",
    );
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
  statusEl.textContent = "";
  showTyping(answerBubble, "질문을 보내는 중…");

  // 조각이 올 때마다 마크다운을 다시 그리되, 화면 갱신 한 번에 한 번만 그린다
  const redraw = () => {
    renderQueued = false;
    if (failed || !answer) return; // 오류 문구를 덮어쓰지 않고, 아직 조각이 없으면 기다림 표시를 둔다
    answerBubble.replaceChildren(renderMarkdown(answer));
    answerBubble.removeAttribute("aria-busy");
    scrollToEnd();
  };
  const showError = (message) => {
    failed = true;
    answerBubble.textContent = message;
    answerBubble.classList.add("error");
    answerBubble.removeAttribute("aria-busy");
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
    try {
      message = (await response.json()).error || message;
    } catch (error) {
      /* 본문이 JSON이 아니면 기본 문장 */
    }
    showError(message);
    return;
  }
  setTypingLabel(answerBubble, "답변을 준비하는 중…");

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
        setTypingLabel(answerBubble, data);
      } else if (name === "token") {
        answer += data;
        if (!renderQueued) {
          renderQueued = true;
          requestAnimationFrame(redraw);
        }
      } else if (name === "sources") {
        showSources(data);
      } else if (name === "done") {
        answer = data.answer || answer; // 조각이 모자라도 전체 답변으로 맞춘다
        redraw();
        if (data.conversation_id) conversationId = data.conversation_id;
      } else if (name === "error") {
        showError(data.message || "오류가 발생했습니다.");
        if (data.conversation_id) conversationId = data.conversation_id; // 질문은 저장됐으니 같은 대화에서 이어간다
      }
    }
  }

  if (!failed) {
    if (answer) redraw();
    else showError("답변이 비어 있습니다. 다시 시도해 주세요."); // 연결이 끝났는데 아무것도 오지 않았다
  }
  loadConversations(); // 새 대화가 생겼거나 제목이 바뀌었을 수 있다
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const question = input.value.trim();
  if (!question || busy) return;
  input.value = "";
  autoGrow();
  busy = true;
  sendButton.disabled = true;
  try {
    await ask(question);
  } catch (error) {
    // 기다림 표시가 남아 있는 말풍선이 있으면 그 자리에 오류를 보여 준다
    const pending =
      messagesEl.querySelector('.bubble[aria-busy="true"]') ||
      addBubble("assistant", "");
    pending.textContent =
      "연결에 문제가 생겼습니다. 인터넷 연결을 확인하고 다시 시도해 주세요.";
    pending.classList.add("error");
    pending.removeAttribute("aria-busy");
  } finally {
    busy = false;
    sendButton.disabled = false;
    input.focus();
  }
});

// 입력창은 글 줄 수만큼 늘어난다 (최대 높이는 CSS의 max-height)
function autoGrow() {
  input.style.height = "auto";
  input.style.height = `${input.scrollHeight}px`;
}
input.addEventListener("input", autoGrow);

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
