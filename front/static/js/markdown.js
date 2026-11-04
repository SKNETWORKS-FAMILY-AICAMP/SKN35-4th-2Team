function isSafeHttpUrl(value) {
  try {
    const url = new URL(value);
    return url.protocol === "https:" || url.protocol === "http:";
  } catch (error) {
    return false;
  }
}

// 한 줄 안의 `코드`, **굵게**, [글자](주소)를 처리한다
const INLINE_PATTERN =
  /(`[^`\n]+`)|(\*\*[^*\n]+\*\*)|(\[[^\]\n]+\]\([^)\s]+\))/g;

function appendInline(parent, text) {
  let last = 0;
  for (const match of text.matchAll(INLINE_PATTERN)) {
    if (match.index > last) parent.append(text.slice(last, match.index));
    const [token] = match;
    if (match[1]) {
      const code = document.createElement("code");
      code.textContent = token.slice(1, -1);
      parent.append(code);
    } else if (match[2]) {
      const strong = document.createElement("strong");
      strong.textContent = token.slice(2, -2);
      parent.append(strong);
    } else {
      const split = token.indexOf("](");
      const label = token.slice(1, split);
      const href = token.slice(split + 2, -1);
      if (isSafeHttpUrl(href)) {
        const link = document.createElement("a");
        link.href = href;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        link.textContent = label;
        parent.append(link);
      } else {
        parent.append(token); // 안전하지 않은 주소는 링크로 만들지 않고 글자 그대로 둔다
      }
    }
    last = match.index + token.length;
  }
  if (last < text.length) parent.append(text.slice(last));
}

function appendLines(parent, lines) {
  lines.forEach((line, index) => {
    if (index > 0) parent.append(document.createElement("br"));
    appendInline(parent, line);
  });
}

async function copyCodeText(text) {
  if (navigator.clipboard && window.isSecureContext) {
    // A denied clipboard permission is reported, rather than bypassed.
    await navigator.clipboard.writeText(text);
    return;
  }
  // HTTP development/deployment: synchronous clipboard fallback during user action.
  const previousFocus = document.activeElement;
  const selection = window.getSelection();
  const ranges = [];
  if (selection) for (let i = 0; i < selection.rangeCount; i++) ranges.push(selection.getRangeAt(i).cloneRange());
  const area = document.createElement("textarea");
  area.value = text;
  area.readOnly = true;
  area.className = "clipboard-fallback";
  document.body.append(area);
  area.select();
  try {
    if (!document.execCommand("copy")) throw new Error("Clipboard unavailable");
  } finally {
    area.remove();
    if (previousFocus && previousFocus.isConnected) previousFocus.focus({ preventScroll: true });
    if (selection) { selection.removeAllRanges(); ranges.forEach(range => selection.addRange(range)); }
  }
}

function renderMarkdown(source) {
  const fragment = document.createDocumentFragment();
  const lines = String(source || "")
    .replace(/\r\n?/g, "\n")
    .split("\n");
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];

    if (!line.trim()) {
      i += 1;
      continue;
    }

    // ``` 코드 블록 (스트리밍 중 아직 닫히지 않았어도 끝까지 코드로 보여 준다)
    const fence = line.match(/^\s*```\s*([\w+-]*)/);
    if (fence) {
      const body = [];
      i += 1;
      while (i < lines.length && !/^\s*```\s*$/.test(lines[i])) {
        body.push(lines[i]);
        i += 1;
      }
      i += 1; // 닫는 ```
      const pre = document.createElement("pre");
      const code = document.createElement("code");
      if (fence[1]) pre.dataset.lang = fence[1];
      code.textContent = body.join("\n");
      pre.append(code);
      const block = document.createElement("div");
      block.className = "code-block";
      const toolbar = document.createElement("div");
      toolbar.className = "code-toolbar";
      const language = document.createElement("span");
      language.textContent = fence[1] || "코드";
      const copy = document.createElement("button");
      copy.type = "button";
      copy.className = "copy-code";
      copy.title = "코드 복사";
      copy.setAttribute("aria-label", "이 코드 블록 복사");
      const notice = document.createElement("span");
      notice.className = "copy-notice";
      notice.setAttribute("role", "status");
      const showIcon = (copied) => {
        const ns = "http://www.w3.org/2000/svg";
        const icon = document.createElementNS(ns, "svg");
        icon.setAttribute("viewBox", "0 0 24 24");
        icon.setAttribute("width", "18");
        icon.setAttribute("height", "18");
        icon.setAttribute("fill", "none");
        icon.setAttribute("stroke", "currentColor");
        icon.setAttribute("stroke-width", "1.6");
        icon.setAttribute("stroke-linecap", "round");
        icon.setAttribute("stroke-linejoin", "round");
        icon.setAttribute("aria-hidden", "true");
        const path = document.createElementNS(ns, "path");
        path.setAttribute("d", copied
          ? "M5 12l4 4L19 6"
          : "M9 5V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2h-1 M4 8h10a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V10a2 2 0 0 1 2-2Z");
        icon.append(path);
        copy.replaceChildren(icon);
      };
      showIcon(false);
      let resetTimer;
      copy.addEventListener("click", async () => {
        clearTimeout(resetTimer);
        copy.disabled = true;
        notice.textContent = "";
        try {
          await copyCodeText(code.textContent);
          showIcon(true);
          copy.title = "복사 완료";
          copy.setAttribute("aria-label", "복사 완료");
          notice.dataset.state = "success";
          notice.textContent = "복사했습니다.";
          resetTimer = setTimeout(() => {
            showIcon(false);
            copy.title = "코드 복사";
            copy.setAttribute("aria-label", "이 코드 블록 복사");
            notice.textContent = "";
          }, 2000);
        } catch (error) {
          showIcon(false);
          copy.title = "다시 복사";
          copy.setAttribute("aria-label", "코드 다시 복사");
          notice.dataset.state = "error";
          notice.textContent = "복사하지 못했습니다. 코드를 선택해 직접 복사해 주세요.";
        } finally { copy.disabled = false; }
      });
      toolbar.append(language, notice, copy);
      block.append(toolbar, pre);
      fragment.append(block);
      continue;
    }

    const heading = line.match(/^(#{1,4})\s+(.*)$/);
    if (heading) {
      const element = document.createElement(
        `h${Math.min(heading[1].length + 2, 6)}`,
      ); // # 는 h3부터 (화면 제목보다 작게)
      appendInline(element, heading[2]);
      fragment.append(element);
      i += 1;
      continue;
    }

    const bullet = /^\s*[-*]\s+(.*)$/;
    const numbered = /^\s*\d+[.)]\s+(.*)$/;
    if (bullet.test(line) || numbered.test(line)) {
      const ordered = numbered.test(line);
      const list = document.createElement(ordered ? "ol" : "ul");
      const pattern = ordered ? numbered : bullet;
      while (i < lines.length && pattern.test(lines[i])) {
        const item = document.createElement("li");
        appendInline(item, lines[i].match(pattern)[1]);
        list.append(item);
        i += 1;
      }
      fragment.append(list);
      continue;
    }

    if (/^\s*>\s?/.test(line)) {
      const quote = document.createElement("blockquote");
      const body = [];
      while (i < lines.length && /^\s*>\s?/.test(lines[i])) {
        body.push(lines[i].replace(/^\s*>\s?/, ""));
        i += 1;
      }
      appendLines(quote, body);
      fragment.append(quote);
      continue;
    }

    // 문단: 빈 줄이나 다른 블록이 나올 때까지
    const paragraph = [];
    while (
      i < lines.length &&
      lines[i].trim() &&
      !/^\s*```/.test(lines[i]) &&
      !/^#{1,4}\s/.test(lines[i]) &&
      !bullet.test(lines[i]) &&
      !numbered.test(lines[i]) &&
      !/^\s*>\s?/.test(lines[i])
    ) {
      paragraph.push(lines[i]);
      i += 1;
    }
    const p = document.createElement("p");
    appendLines(p, paragraph);
    fragment.append(p);
  }
  return fragment;
}
