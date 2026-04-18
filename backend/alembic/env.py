import os
import sys
from logging.config import fileConfig

from dotenv import load_dotenv
from sqlalchemy import create_engine

from alembic import context

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
load_dotenv()

from database import Base  # noqa: E402
import models  # noqa: E402, F401  (registers tables on Base.metadata)

DB = os.getenv("DATABASE_URL")
if not DB:
    raise RuntimeError("DATABASE_URL not set — cannot run migrations")

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=DB,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(DB)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
