"""
저장할 텍스트의 길이 상한.

왜 필요한가: TiDB Cloud Starter는 한 행의 최대 크기가 6,291,456바이트(6MiB)다 (2026-10-08 실제 시험으로 확인,
넘으면 오류 8025 "entry too large"). 사용자가 아주 긴 로그를 붙여 넣으면 이 한도를 넘어 DB 오류가 나므로,
그 전에 이해하기 쉬운 오류로 막거나(사용자 입력) 잘라서(모델이 만든 텍스트) 저장한다.

글자 수 상한은 한글 3바이트, 이모지 4바이트로 계산해도 6MiB에 한참 못 미치게 잡았다.
환경변수로 바꿀 수 있고, 비워 두면 기본값을 쓴다.
"""

import os

from src.const import db_config as cfg

CLIP_SUFFIX = cfg.CLIP_SUFFIX  # 값과 기본값은 src/const/db_config.py에 있다


def _env_int(name: str, default: int) -> int:
    return int(os.getenv(name) or default)


def message_max_chars() -> int:
    """질문/답변 한 건의 최대 글자 수 (MESSAGE_MAX_CHARS, 기본은 db_config.DEFAULT_MESSAGE_MAX_CHARS)."""
    return _env_int("MESSAGE_MAX_CHARS", cfg.DEFAULT_MESSAGE_MAX_CHARS)


def snippet_max_chars() -> int:
    """답변 출처의 발췌문 최대 글자 수 (SNIPPET_MAX_CHARS, 기본은 db_config.DEFAULT_SNIPPET_MAX_CHARS)."""
    return _env_int("SNIPPET_MAX_CHARS", cfg.DEFAULT_SNIPPET_MAX_CHARS)


def summary_max_chars() -> int:
    """대화 요약 최대 글자 수 (SUMMARY_MAX_CHARS, 기본은 db_config.DEFAULT_SUMMARY_MAX_CHARS)."""
    return _env_int("SUMMARY_MAX_CHARS", cfg.DEFAULT_SUMMARY_MAX_CHARS)


def clip_text(text: str | None, max_chars: int) -> str | None:
    """max_chars를 넘으면 잘라서 끝에 표시를 붙인다. 넘지 않으면 그대로."""
    if text and len(text) > max_chars:
        return text[:max_chars] + CLIP_SUFFIX
    return text
