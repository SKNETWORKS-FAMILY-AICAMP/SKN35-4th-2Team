"""
초기 계정 만들기 (관리자 / 테스트 사용자).

비밀번호는 코드에 적지 않고 환경변수(.env)에서만 읽는다. 저장소에는 올라가지 않는다.
    SEED_ADMIN_USERNAME / SEED_ADMIN_PASSWORD
    SEED_USER_USERNAME  / SEED_USER_PASSWORD
값이 없으면 그 계정은 건너뛴다. 이미 있는 계정도 건너뛴다 (여러 번 실행해도 안전).

실행: python -m src.db.seed   (프로젝트 루트에서)
"""

import os

from sqlalchemy import select
from sqlalchemy.orm import Session

from .engine import init_db, make_engine, make_session_factory, session_scope
from .models import User
from .repository import create_user, normalize_username

_ACCOUNTS = (("SEED_ADMIN", True), ("SEED_USER", False))


def seed(session: Session) -> list[str]:
    """새로 만든 아이디 목록을 돌려준다 (비밀번호는 돌려주지도, 출력하지도 않는다)."""
    created: list[str] = []
    for prefix, is_admin in _ACCOUNTS:
        name = os.getenv(f"{prefix}_USERNAME")
        password = os.getenv(f"{prefix}_PASSWORD")
        if not name or not password:
            continue
        exists = session.scalar(select(User).where(User.username == normalize_username(name)))
        if exists:
            continue
        create_user(session, name, password, is_admin=is_admin)
        created.append(normalize_username(name))
    return created


if __name__ == "__main__":
    try:
        from dotenv import load_dotenv

        # ENV_FILE=.env.tidb 처럼 지정하면 그 파일을 읽고 기존 환경변수보다 우선한다 (기본은 .env, 덮어쓰지 않음).
        env_file = os.getenv("ENV_FILE")
        load_dotenv(env_file or None, override=bool(env_file))
    except ImportError:
        pass

    engine = make_engine()
    init_db(engine)
    with session_scope(make_session_factory(engine)) as session:
        done = seed(session)
    print("새로 만든 계정:", done or "없음 (이미 있거나 SEED_* 환경변수가 비어 있음)")
    print("접속 대상:", engine.url.render_as_string(hide_password=True))
