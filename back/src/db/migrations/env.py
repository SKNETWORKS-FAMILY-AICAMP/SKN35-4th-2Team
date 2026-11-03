"""alembic 실행 환경. 접속 정보는 engine.py와 같은 규칙으로 읽는다."""

from alembic import context

try:  # .env가 있으면 읽는다 (alembic CLI는 seed.py처럼 따로 읽어야 한다)
    import os

    from dotenv import load_dotenv

    # ENV_FILE=.env.tidb 처럼 지정하면 그 파일을 읽고 기존 환경변수보다 우선한다 (기본은 .env, 덮어쓰지 않음).
    env_file = os.getenv("ENV_FILE")
    load_dotenv(env_file or None, override=bool(env_file))
except ImportError:
    pass

from src.db.engine import make_engine
from src.db.models import Base

target_metadata = Base.metadata


def run_migrations_online() -> None:
    # 테스트처럼 이미 열린 연결을 넘기면 그걸 쓰고, 아니면 .env 설정으로 새로 연결한다.
    connection = context.config.attributes.get("connection")
    if connection is not None:
        _migrate(connection)
        return
    engine = make_engine()
    with engine.connect() as conn:
        _migrate(conn)
    engine.dispose()


def _migrate(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        # SQLite는 ALTER가 제한적이라 일부 변경을 테이블 재생성으로 처리한다.
        render_as_batch=connection.dialect.name == "sqlite",
    )
    with context.begin_transaction():
        context.run_migrations()


run_migrations_online()
