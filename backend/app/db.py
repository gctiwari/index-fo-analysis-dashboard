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
    """
    SQLAlchemy's create_all() only creates missing TABLES -- it never alters
    an existing table's columns. If the schema has drifted from an older
    version of this app (e.g. before the `role` or monitoring-diagnostics
    columns existed), old queries would crash. Per explicit product
    decision, preserving old tracking.db history across schema changes is
    NOT a requirement for this prototype -- a fresh database is entirely
    acceptable, so this just drops and recreates on any detected drift
    rather than maintaining a migration system. If you want to keep old
    history across a schema change, back up tracking.db yourself first.
    """
    _reset_db_if_schema_drifted()
    from app import models_db  # noqa: F401  (ensure models are registered)
    Base.metadata.create_all(bind=engine)


def _reset_db_if_schema_drifted():
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
    # Canary column is always the newest one added -- if it's missing, the schema is stale.
    if cols and "unique_candles_checked" not in cols:
        os.remove(db_path)
        print(f"[tracking DB] Schema drift detected -- reset {db_path} to a fresh database (old history not preserved, by design).")  # noqa: T201
