"""
DB 연결 (엔진 / 세션).

접속 정보를 읽는 우선순위
1. DATABASE_URL            (전체 접속 문자열을 직접 지정. 테스트나 다른 DB용)
2. DB_HOST + DB_USERNAME   (TiDB Cloud. .env에 DB_PORT, DB_PASSWORD, DB_DATABASE, DB_SSL_CA)
3. 아무것도 없으면 로컬 SQLite 파일 (인터넷이 없을 때를 위한 비상용, 데이터는 공유되지 않는다)

2차 프로젝트(app/shared/db.py)에서 겪은 것들을 그대로 반영했다.
- 비밀번호에 @ : / 같은 문자가 있어도 접속 문자열이 깨지지 않게 URL.create를 쓴다.
- TiDB Cloud는 TLS가 필수라서 certifi 인증서 번들을 기본으로 쓰고 DB_SSL_CA로 바꿀 수 있다.
  로컬 MySQL(localhost)에서는 TLS를 끈다. 직접 정하려면 DB_SSL=true/false (use_tls 참고).
- .env 키에 DB_ 접두사를 붙인다 (Windows가 USERNAME을 이미 쓰고 있어서 충돌한다).
- 끊긴 연결을 감지하려고 pool_pre_ping=True.
"""

import os
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import URL, Engine, make_url
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from src.const import db_config as cfg

from .models import Base

# 드라이버, 기본 포트, 문자셋, 로컬 주소 목록, 비상용 SQLite 경로는 src/const/db_config.py에 있다.


def build_url() -> URL:
    explicit = os.getenv("DATABASE_URL")
    if explicit:
        return make_url(explicit)

    host, user = os.getenv("DB_HOST"), os.getenv("DB_USERNAME")
    if host and user:
        return URL.create(
            drivername=cfg.DB_DRIVER,
            username=user,
            password=os.getenv("DB_PASSWORD", ""),
            host=host,
            port=int(os.getenv("DB_PORT") or cfg.DEFAULT_DB_PORT),
            database=os.getenv("DB_DATABASE", ""),
            query={"charset": cfg.DB_CHARSET},
        )

    cfg.LOCAL_SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
    return URL.create("sqlite", database=str(cfg.LOCAL_SQLITE_PATH))


def use_tls(url: URL) -> bool:
    """TLS(암호화 연결)를 쓸지 정한다.

    - DB_SSL이 true/false로 지정되어 있으면 그대로 따른다.
    - 지정이 없으면: 로컬 주소(localhost 등)는 끄고, 그 밖의 서버(TiDB Cloud 등)는 켠다.
      TiDB Cloud는 TLS가 필수이고, 로컬 MySQL은 보통 TLS 설정이 없어서 켜면 접속이 실패한다.
    """
    flag = (os.getenv("DB_SSL") or "").strip().lower()
    if flag:
        return flag in ("1", "true", "yes", "on")
    return (url.host or "").lower() not in cfg.LOCAL_HOSTS


def _tls_args() -> dict:
    ca = os.getenv("DB_SSL_CA")
    if not ca:
        try:
            import certifi

            ca = certifi.where()
        except ImportError:
            return {"ssl": {}}
    return {"ssl": {"ca": ca}}


def make_engine(url: URL | str | None = None) -> Engine:
    url = make_url(url) if isinstance(url, str) else (url or build_url())

    if url.drivername.startswith("sqlite"):
        kwargs: dict = {}
        if url.database in (None, "", ":memory:"):
            # 메모리 DB는 연결마다 새 DB가 되므로 하나의 연결을 공유시킨다 (테스트용).
            kwargs = {"poolclass": StaticPool, "connect_args": {"check_same_thread": False}}
        return create_engine(url, **kwargs)

    if url.drivername.startswith("mysql"):
        return create_engine(
            url, connect_args=_tls_args() if use_tls(url) else {}, pool_pre_ping=True
        )

    return create_engine(url, pool_pre_ping=True)


def init_db(engine: Engine) -> None:
    """테이블이 없으면 만든다 (있으면 건드리지 않는다). 컬럼 변경은 만들어 주지 않는다."""
    Base.metadata.create_all(engine)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    """with 블록이 정상 종료되면 commit, 예외가 나면 rollback 한다."""
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
