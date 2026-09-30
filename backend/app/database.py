"""SQLite connection setup for the backend."""

from collections.abc import Generator
from datetime import datetime, timezone
from pathlib import Path
from sqlite3 import Connection as SQLiteConnection

from sqlalchemy import DateTime, create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker
from sqlalchemy.types import TypeDecorator


DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "app.db"
DATABASE_URL = f"sqlite:///{DB_PATH.as_posix()}"

def create_sqlite_engine(database_url: str) -> Engine:
    """Configure every new SQLite connection before it is used by the app."""
    sqlite_engine = create_engine(
        database_url,
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(sqlite_engine, "connect")
    def enable_foreign_keys(connection: SQLiteConnection, connection_record: object) -> None:
        cursor = connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()

    return sqlite_engine


engine = create_sqlite_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


class UTCDateTime(TypeDecorator):
    """Store UTC in SQLite and return timezone-aware UTC datetimes."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: object) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("datetime must include a timezone offset")
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: object) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


def get_db() -> Generator[Session, None, None]:
    """Provide one database session for a request, then close it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
