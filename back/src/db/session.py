"""
간편 접근 함수 - 다른 코드(LangGraph, UI, MCP 서버)가 DB를 한 줄로 쓰게 한다.

    from src.db.session import db_session
    from src.db import authenticate, add_message

    with db_session() as s:                 # 정상 종료하면 commit, 예외가 나면 rollback
        user = authenticate(s, "alice", "...")

엔진과 세션 팩토리는 프로세스에서 한 번만 만들어 재사용한다 (매번 만들면 연결이 계속 늘어난다).
접속 정보는 engine.py와 같은 규칙으로 읽고, 처음 쓸 때 .env(또는 ENV_FILE로 지정한 파일)를 한 번 읽는다.
이미 설정된 환경변수는 .env 값으로 덮어쓰지 않는다.
"""

import os
from contextlib import contextmanager
from functools import lru_cache
from typing import Iterator

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .engine import make_engine, make_session_factory, session_scope


def _load_env() -> None:
    """.env를 읽는다. ENV_FILE로 파일을 직접 지정했다면 그 값이 이미 설정된 환경변수보다 우선한다.

    왜: 다른 모듈(예: src/const/config.py)이 먼저 .env를 읽어 DB_* 값(로컬 MySQL)을 올려 두었을 수 있다.
    ENV_FILE=.env.tidb처럼 명시적으로 고른 경우에도 덮어쓰지 않으면, TiDB를 가리킨 줄 알았는데
    로컬 MySQL로 접속하는 일이 생긴다. ENV_FILE을 지정하지 않았을 때는 기존 환경변수를 그대로 둔다.
    """
    try:
        from dotenv import load_dotenv
    except ImportError:  # python-dotenv가 없으면 이미 설정된 환경변수만 쓴다
        return
    env_file = os.getenv("ENV_FILE")
    load_dotenv(env_file or None, override=bool(env_file))


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    _load_env()
    return make_engine()


@lru_cache(maxsize=1)
def get_session_factory() -> sessionmaker[Session]:
    return make_session_factory(get_engine())


@contextmanager
def db_session() -> Iterator[Session]:
    """with 블록 하나가 트랜잭션 하나다. 정상 종료하면 commit, 예외가 나면 rollback."""
    with session_scope(get_session_factory()) as session:
        yield session


def reset_engine() -> None:
    """캐시된 엔진을 닫고 버린다. 접속 설정(환경변수)을 바꾼 뒤 다시 연결해야 할 때, 그리고 테스트용."""
    if get_engine.cache_info().currsize:
        get_engine().dispose()
    get_session_factory.cache_clear()
    get_engine.cache_clear()
