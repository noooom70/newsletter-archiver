"""SQLAlchemy models and database setup."""

from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    create_engine,
    inspect,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


class Newsletter(Base):
    __tablename__ = "newsletters"

    id = Column(Integer, primary_key=True, autoincrement=True)
    message_id = Column(String, unique=True, nullable=False, index=True)
    subject = Column(String, nullable=False)
    sender_email = Column(String, nullable=False, index=True)
    sender_name = Column(String, default="")
    received_date = Column(DateTime, nullable=False, index=True)
    markdown_path = Column(String)
    html_path = Column(String)
    word_count = Column(Integer, default=0)
    reading_time_minutes = Column(Float, default=0.0)
    tags = Column(String, default="")  # comma-separated
    category = Column(String, default="")
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))

    def __repr__(self) -> str:
        return f"<Newsletter {self.subject!r} from {self.sender_email}>"


class Sender(Base):
    __tablename__ = "senders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String, unique=True, nullable=False, index=True)
    name = Column(String, default="")
    status = Column(String, default="pending", index=True)  # pending, approved, denied
    mode = Column(String, default="review")  # auto or review
    sample_subject = Column(String, default="")  # example subject line for review
    first_seen = Column(DateTime, default=lambda: datetime.now(UTC))

    def __repr__(self) -> str:
        return f"<Sender {self.email} ({self.status})>"


class EmbeddingChunk(Base):
    __tablename__ = "embedding_chunks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    newsletter_id = Column(Integer, nullable=False, index=True)
    chunk_index = Column(Integer, nullable=False)
    chunk_text = Column(Text, nullable=False)


class PendingEmail(Base):
    __tablename__ = "pending_emails"

    id = Column(Integer, primary_key=True, autoincrement=True)
    message_id = Column(String, unique=True, nullable=False, index=True)
    subject = Column(String, nullable=False)
    sender_email = Column(String, nullable=False, index=True)
    sender_name = Column(String, default="")
    received_date = Column(DateTime, nullable=False)
    html_body = Column(Text, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))

    def __repr__(self) -> str:
        return f"<PendingEmail {self.subject!r} from {self.sender_email}>"


def get_engine(db_url: str):
    return create_engine(db_url, echo=False)


def create_tables(db_url: str) -> None:
    """Create all tables if they don't exist, and migrate schema."""
    engine = get_engine(db_url)
    Base.metadata.create_all(engine)
    _migrate(engine)
    _create_fts_table(engine)


def _create_fts_table(engine) -> None:
    """Create FTS5 virtual table if it doesn't exist (raw SQL — not supported by SQLAlchemy DDL)."""
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE VIRTUAL TABLE IF NOT EXISTS newsletters_fts USING fts5(
                subject, content, sender_name,
                newsletter_id UNINDEXED,
                tokenize='porter unicode61'
            )
        """))


def _migrate(engine) -> None:
    """Add columns that may be missing from older databases."""
    inspector = inspect(engine)

    # Add senders.mode if missing (added in auto/review feature)
    if "senders" in inspector.get_table_names():
        columns = {col["name"] for col in inspector.get_columns("senders")}
        if "mode" not in columns:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE senders ADD COLUMN mode VARCHAR DEFAULT 'review'"))


def get_session(db_url: str) -> Session:
    """Get a new database session."""
    engine = get_engine(db_url)
    return sessionmaker(bind=engine)()
