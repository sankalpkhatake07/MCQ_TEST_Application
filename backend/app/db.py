from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import inspect, text
from sqlmodel import Session, SQLModel, create_engine

from . import config

_url = config.DATABASE_URL
_args = {}
if _url.startswith("sqlite"):
    _args = {"check_same_thread": False, "timeout": 30}
    path = _url.replace("sqlite:///", "", 1)
    if path and path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(_url, connect_args=_args, pool_pre_ping=True)


def init_db():
    from . import models  # noqa: F401  (register tables)
    SQLModel.metadata.create_all(engine)
    _add_missing_columns()


def _add_missing_columns():
    """Tiny forward-only migration: add nullable columns that newer model versions introduced.
    For real production schema changes use Alembic."""
    insp = inspect(engine)
    for table in SQLModel.metadata.sorted_tables:
        if not insp.has_table(table.name):
            continue
        have = {c["name"] for c in insp.get_columns(table.name)}
        for col in table.columns:
            if col.name not in have:
                ddl = col.type.compile(dialect=engine.dialect)
                with engine.begin() as conn:
                    conn.execute(text(f'ALTER TABLE {table.name} ADD COLUMN {col.name} {ddl}'))


def get_session():
    with Session(engine) as s:
        yield s


@contextmanager
def startup_lock():
    """Several replicas start at once behind the load balancer: let only one create tables / seed data at a time."""
    name = engine.dialect.name
    if name not in ("postgresql", "mysql"):
        yield
        return
    conn = engine.connect()
    try:
        conn.execute(text("SELECT pg_advisory_lock(727274)" if name == "postgresql" else "SELECT GET_LOCK('examhub_init', 60)"))
        yield
    finally:
        try:
            conn.execute(text("SELECT pg_advisory_unlock(727274)" if name == "postgresql" else "SELECT RELEASE_LOCK('examhub_init')"))
        finally:
            conn.close()
