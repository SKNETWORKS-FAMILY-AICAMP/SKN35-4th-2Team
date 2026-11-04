"""Use exactly the chat database configuration, including back/.env."""
import os
from pathlib import Path
from dotenv import load_dotenv
from alembic import context
from src.db.engine import make_engine
from chat.pins import metadata

env_file = os.getenv("ENV_FILE")
load_dotenv(env_file or Path(__file__).resolve().parents[2] / ".env", override=bool(env_file))

def migrate(connection):
    context.configure(connection=connection, target_metadata=metadata,
                      version_table="conversation_pins_alembic_version", render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()

connection = context.config.attributes.get("connection")
if connection is not None:
    migrate(connection)
else:
    engine = make_engine()
    try:
        with engine.connect() as connection:
            migrate(connection)
    finally:
        engine.dispose()
