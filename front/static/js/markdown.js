// 답변의 마크다운(제목, 목록, 코드, 굵게, 링크)을 화면 요소로 바꾼다.
// 안전을 위해 HTML 문자열을 만들지 않고, 요소를 직접 만든 뒤 textContent로만 글을 넣는다.
// (답변에 <script> 같은 글이 있어도 그냥 글자로 보인다.) 링크는 http/https만 허용한다.
//
// 사용: container.replaceChildren(renderMarkdown(text))

function isSafeHttpUrl(value) {
  try {
    const url = new URL(value);
    return url.protocol === "https:" || url.protocol === "http:";
  } catch (error) {
    return false;
  }
}

// 한 줄 안의 `코드`, **굵게**, [글자](주소)를 처리한다
const INLINE_PATTERN = /(`[^`\n]+`)|(\*\*[^*\n]+\*\*)|(\[[^\]\n]+\]\([^)\s]+\))/g;

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

function renderMarkdown(source) {
  const fragment = document.createDocumentFragment();
  const lines = String(source || "").replace(/\r\n?/g, "\n").split("\n");
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];

    if (!line.trim()) { i += 1; continue; }

    // ``` 코드 블록 (스트리밍 중 아직 닫히지 않았어도 끝까지 코드로 보여 준다)
    const fence = line.match(/^\s*```\s*([\w+-]*)/);
    if (fence) {
      const body = [];
      i += 1;
      while (i < lines.length && !/^\s*```\s*$/.test(lines[i])) { body.push(lines[i]); i += 1; }
      i += 1; // 닫는 ```
      const pre = document.createElement("pre");
      const code = document.createElement("code");
      if (fence[1]) pre.dataset.lang = fence[1];
      code.textContent = body.join("\n");
      pre.append(code);
      fragment.append(pre);
      continue;
    }

    const heading = line.match(/^(#{1,4})\s+(.*)$/);
    if (heading) {
      const element = document.createElement(`h${Math.min(heading[1].length + 2, 6)}`); // # 는 h3부터 (화면 제목보다 작게)
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
      while (i < lines.length && /^\s*>\s?/.test(lines[i])) { body.push(lines[i].replace(/^\s*>\s?/, "")); i += 1; }
      appendLines(quote, body);
      fragment.append(quote);
      continue;
    }

    // 문단: 빈 줄이나 다른 블록이 나올 때까지
    const paragraph = [];
    while (i < lines.length && lines[i].trim() && !/^\s*```/.test(lines[i]) && !/^#{1,4}\s/.test(lines[i])
      && !bullet.test(lines[i]) && !numbered.test(lines[i]) && !/^\s*>\s?/.test(lines[i])) {
      paragraph.push(lines[i]);
      i += 1;
    }
    const p = document.createElement("p");
    appendLines(p, paragraph);
    fragment.append(p);
  }
  return fragment;
}
