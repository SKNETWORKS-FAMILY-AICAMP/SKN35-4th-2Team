"""
대화 이력을 "다음 질문에 얼마나 반영할지" 정하는 로직.

DB를 직접 건드리지 않는 순수 함수라서 테스트하기 쉽다.

반영량을 제한하는 두 가지 상한 (둘 다 .env나 설정으로 바꿀 수 있다)
- max_turns : 최근 몇 번의 주고받음(질문+답변 한 쌍)까지 볼지
- max_tokens: 이력 전체가 차지할 수 있는 토큰 예산

기본값은 임의로 잡은 시작값이다. 평가하면서 조정해야 한다.
"""

import os
from dataclasses import dataclass
from typing import Sequence

from src.const import db_config as cfg


@dataclass(frozen=True)
class HistoryConfig:
    # 기본값은 src/const/db_config.py에 있다
    max_turns: int = cfg.DEFAULT_HISTORY_MAX_TURNS
    max_tokens: int = cfg.DEFAULT_HISTORY_MAX_TOKENS

    @classmethod
    def from_env(cls) -> "HistoryConfig":
        # 환경변수가 비어 있어도(.env.example을 복사해 "HISTORY_MAX_TURNS=" 처럼 둔 경우) 기본값을 쓴다.
        return cls(
            max_turns=int(os.getenv("HISTORY_MAX_TURNS") or cls.max_turns),
            max_tokens=int(os.getenv("HISTORY_MAX_TOKENS") or cls.max_tokens),
        )


def estimate_tokens(text: str) -> int:
    """아주 거친 추정치(글자 수 / 3). 실제 토큰 수는 모델마다 다르다.

    정확한 값이 필요해지면 사용하는 모델의 토크나이저로 교체한다.
    교체 지점을 한 곳으로 모으려고 함수로 분리해 두었다.
    """
    return max(1, len(text) // cfg.TOKEN_ESTIMATE_DIVISOR)


def _truncate_to_tokens(text: str, max_tokens: int) -> str:
    max_chars = max(1, max_tokens * cfg.TOKEN_ESTIMATE_DIVISOR)
    return text if len(text) <= max_chars else text[:max_chars] + " …(이하 생략)"


def select_history(
    messages: Sequence[dict],
    summary: str | None = None,
    config: HistoryConfig = HistoryConfig(),
) -> list[dict]:
    """다음 질문에 붙일 이력을 고른다.

    messages: 시간순(오래된 것 먼저) 리스트. 각 항목은 {"role", "content", "token_count"}.
    반환: [{"role": ..., "content": ...}, ...]

    규칙
    1. 최근 max_turns * 2 개 메시지만 후보로 본다.
    2. 토큰 합이 예산을 넘으면 가장 오래된 메시지부터 버린다.
    3. 이력이 질문(user)으로 시작하도록, 맨 앞에 남은 답변(assistant)은 버린다.
    4. 요약이 있으면 맨 앞에 붙인다 (요약은 예산의 일부로 계산, 최대 1/3).
    5. 가장 최근 메시지 하나가 예산보다 크면 내용을 잘라서라도 넣는다.
    """
    window = list(messages[-config.max_turns * 2 :]) if config.max_turns > 0 else []
    summary_text = None
    if summary:
        # 요약은 예산의 최대 1/3까지만 쓴다. 최근 대화가 요약에 밀려나지 않게 하려는 것.
        summary_text = _truncate_to_tokens(summary, config.max_tokens // 3)
    budget = config.max_tokens - (estimate_tokens(summary_text) if summary_text else 0)

    def cost(m: dict) -> int:
        return m.get("token_count") or estimate_tokens(m["content"])

    kept = list(window)
    while len(kept) > 1 and sum(cost(m) for m in kept) > budget:
        kept.pop(0)
    while kept and kept[0]["role"] != "user" and len(kept) > 1:
        kept.pop(0)

    result: list[dict] = []
    if summary_text:
        result.append({"role": "system", "content": f"[이전 대화 요약] {summary_text}"})
    for m in kept:
        content = m["content"]
        if len(kept) == 1 and cost(m) > budget:
            content = _truncate_to_tokens(content, max(budget, 1))
        result.append({"role": m["role"], "content": content})
    return result
