"""
DATABASE_URL defaults to a local SQLite file so the prototype runs with zero
setup. For production, set DATABASE_URL to a Postgres DSN, e.g.:
    postgresql+psycopg2://user:pass@localhost:5432/indexfo
No other code changes needed -- SQLAlchemy handles both.
"""
from __future__ import annotations
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./tracking.db")

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    _migrate_if_needed()
    from app import models_db  # noqa: F401  (ensure models are registered)
    Base.metadata.create_all(bind=engine)


def _migrate_if_needed():
    """
    SQLAlchemy's create_all() only creates missing TABLES -- it never alters
    an existing table's columns. If you're upgrading from an older version of
    this app (before the `role` column, or before these monitoring-diagnostic
    columns existed), the old tracking.db would crash every query instead of
    just working. Since this is a SQLite prototype without a real migration
    tool (Alembic), the safe fallback is: detect the old schema, move it
    aside, and let a fresh one get created. This means old trade history
    isn't silently lost -- it's renamed, not deleted. The canary column
    checked here is always the newest one added, so any older schema
    (missing `role`, or missing the diagnostics columns, or both) is caught.
    """
    if not DATABASE_URL.startswith("sqlite"):
        return  # Postgres deployments should manage schema changes via a real migration tool
    db_path = DATABASE_URL.replace("sqlite:///", "")
    if not os.path.exists(db_path):
        return
    import sqlite3
    conn = sqlite3.connect(db_path)
    try:
        cols = [row[1] for row in conn.execute("PRAGMA table_info(recommendations)").fetchall()]
    except sqlite3.OperationalError:
        cols = []
    conn.close()
    if cols and "monitor_tick_count" not in cols:
        import time
        backup_path = f"{db_path}.pre-diagnostics-migration-{int(time.time())}.bak"
        os.rename(db_path, backup_path)
        print(  # noqa: T201 -- deliberately visible at startup, not just logged
            f"[tracking DB] Old schema detected (missing monitoring-diagnostics columns added during the "
            f"trigger-execution RCA fix). Moved it to {backup_path} and starting a fresh database. "
            f"Your old trade history is preserved in that backup file but won't appear in the app anymore."
        )
