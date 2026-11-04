"""
저장 전에 텍스트 속 비밀(API 키, 토큰, 비밀번호 등)을 가린다.

왜 필요한가: 사용자가 붙여 넣는 오류 메시지와 코드에는 API 키나 접속 문자열이 섞이기 쉽고,
이 DB는 외부(TiDB Cloud)에 있다. 한번 저장되면 지우기 어렵다.

한계 (중요)
- 알려진 패턴만 가린다. 패턴에 없는 형태의 비밀은 못 거른다. 완벽한 보호가 아니라 "흔한 실수 방지"다.
- 반대로 키처럼 생긴 일반 문자열을 가릴 수도 있다 (예: 문서에 나온 가짜 예시 키).
- 이 함수는 저장할 때만 쓴다. LLM에 보내는 입력에도 쓸지는 파이프라인 쪽에서 따로 정해야 한다.
"""

import re

# (이름, 패턴) — 위에서부터 차례로 적용된다. 이름은 [MASKED:이름]으로 남아 어떤 종류였는지 알 수 있다.
_RULES: list[tuple[str, re.Pattern]] = [
    ("nvidia-key", re.compile(r"\bnvapi-[A-Za-z0-9_\-]{20,}")),
    ("github-token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}|\bgithub_pat_[A-Za-z0-9_]{30,}")),
    ("aws-access-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("api-key", re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}")),
    ("bearer-token", re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._\-]{16,}")),
    # scheme://user:password@host 형태의 접속 문자열에서 비밀번호 부분만
    ("url-password", re.compile(r"(?<=://)([^/\s:@]+):([^/\s@]+)(?=@)")),
]

# KEY=value / "key": "value" 형태 (이름에 비밀을 뜻하는 단어가 들어간 경우만 값을 가린다)
# LLM 개발 질문에는 max_tokens=1500, token_count, tokenizer 같은 코드가 흔해서,
# "token" 뒤에 s / _count / _limit / _usage / izer가 오면 비밀로 보지 않는다.
# 이름은 비밀을 뜻하는 단어부터 찾는다. 단어 앞쪽 글자는 매칭에 넣지 않아도 결과 글에 그대로 남는다
# (앞쪽을 매칭에 넣으면 공백 없이 길게 이어진 글(base64, 압축된 코드 등)에서 시작 위치마다 끝까지 다시 훑어서
#  글 길이의 제곱만큼 느려진다. 예전에는 16,000자에 7초, 20만 자는 사실상 멈췄다).
# 단어 뒤쪽 이름 글자는 100자까지만 본다 (같은 이유로 상한이 필요하고, 실제 키 이름은 길어야 50자 안팎이다).
_ASSIGN = re.compile(
    r"""(?ix)
    (?P<name>(?:password|passwd|secret|api[_\-]?key|access[_\-]?key|token(?!s\b|s_|_count|_limit|_usage|_len|izer))[A-Za-z0-9_\-]{0,100})
    (?P<sep>["']?\s*[:=]\s*["']?)
    (?P<value>[^\s"',;]{4,})
    """
)

# 값이 실제 비밀이 아니라 코드 표현이거나 자리표시자면 그대로 둔다.
_NOT_A_SECRET_VALUES = {"none", "null", "true", "false", "undefined"}


def _looks_like_code_or_placeholder(value: str) -> bool:
    return (
        "(" in value                      # os.getenv(  같은 함수 호출
        or value.lower() in _NOT_A_SECRET_VALUES
        or value[0] in "$%<{"             # ${VAR}, %(name)s, <your-key>, {{ var }}
        or value.startswith("[MASKED")    # 이미 가려진 값
    )


# 비밀키 블록(PEM)은 시작 표시부터 끝 표시까지 통째로 가린다.
# 하나의 정규식(.*?)으로 쓰면 끝 표시가 없는 글에서 시작 표시마다 글 끝까지 다시 훑어 느려지므로 직접 짝을 맞춘다.
_PEM_BEGIN = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")
_PEM_END = re.compile(r"-----END [A-Z ]*PRIVATE KEY-----")


def _mask_private_keys(text: str) -> str:
    parts: list[str] = []
    pos = 0
    while True:
        begin = _PEM_BEGIN.search(text, pos)
        if begin is None:
            break
        end = _PEM_END.search(text, begin.end())
        if end is None:
            break  # 뒤에 끝 표시가 하나도 없으면, 이후의 시작 표시도 짝이 없다
        parts.append(text[pos : begin.start()])
        parts.append("[MASKED:private-key]")
        pos = end.end()
    parts.append(text[pos:])
    return "".join(parts)


def mask_secrets(text: str) -> str:
    if not text:
        return text

    text = _mask_private_keys(text)

    for name, pattern in _RULES:
        if name == "bearer-token":
            text = pattern.sub(lambda m: f"{m.group(1)} [MASKED:{name}]", text)
        elif name == "url-password":
            text = pattern.sub(lambda m: f"{m.group(1)}:[MASKED:{name}]", text)
        else:
            text = pattern.sub(f"[MASKED:{name}]", text)

    def _assign(m: re.Match) -> str:
        if _looks_like_code_or_placeholder(m.group("value")):
            return m.group(0)
        return f"{m.group('name')}{m.group('sep')}[MASKED:secret]"

    return _ASSIGN.sub(_assign, text)
