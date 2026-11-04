"""
도구 파일들이 같이 쓰는 함수: 공개 API 호출(오류를 모델이 읽을 수 있는 문장으로), 결과 만들기.

- 사용자가 고칠 수 있는 오류나 외부 서비스의 실패는 ToolError로 던진다. 이 메시지가 클라이언트와 모델에게 전달된다.
  (그 밖의 예외는 서버 안의 오류로 보고 "Error executing tool ..."만 전달된다.)
- 외부 요청 결과는 HTTP_CACHE_SECONDS 동안 기억해서 요청 제한을 아낀다.
"""

import asyncio
import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

from mcp.server.mcpserver.exceptions import ToolError

from src.const import mcp_config as cfg

_CACHE: dict[str, tuple[float, Any]] = {}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def clip(text: str | None, limit: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[:limit] + cfg.CLIP_SUFFIX


def dump(data: dict) -> str:
    """도구가 돌려주는 글. 모델이 값을 그대로 옮겨 쓸 수 있게 JSON으로 준다."""
    return json.dumps(data, ensure_ascii=False, indent=1)


def _fetch(url: str, headers: dict[str, str]) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": cfg.HTTP_USER_AGENT, **headers})
    with urllib.request.urlopen(request, timeout=cfg.HTTP_TIMEOUT_SECONDS) as response:
        return json.load(response)


def _reset_time(error: urllib.error.HTTPError) -> str:
    reset = error.headers.get("X-RateLimit-Reset") if error.headers else None
    if reset and reset.isdigit():
        return datetime.fromtimestamp(int(reset), timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    return ""


async def fetch_json(url: str, *, headers: dict[str, str] | None = None, what: str = "외부 서비스") -> Any:
    """공개 API에서 JSON을 가져온다. 실패하면 이유를 담은 ToolError를 던진다."""
    cached = _CACHE.get(url)
    if cached and time.monotonic() - cached[0] < cfg.HTTP_CACHE_SECONDS:
        return cached[1]
    try:
        data = await asyncio.to_thread(_fetch, url, headers or {})
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise ToolError(f"{what}에서 찾을 수 없습니다 (404).") from exc
        if exc.code in (403, 429):
            reset = _reset_time(exc)
            when = f" {reset} UTC 이후에 다시 시도할 수 있습니다." if reset else " 잠시 뒤에 다시 시도해야 합니다."
            raise ToolError(f"{what}의 요청 제한에 걸렸습니다 ({exc.code}).{when}") from exc
        raise ToolError(f"{what} 요청이 실패했습니다 (HTTP {exc.code}).") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ToolError(f"{what}에 연결하지 못했습니다. 네트워크를 확인해야 합니다.") from exc
    except ValueError as exc:  # JSON이 아닌 응답
        raise ToolError(f"{what}의 응답을 읽지 못했습니다.") from exc
    _CACHE[url] = (time.monotonic(), data)
    return data
