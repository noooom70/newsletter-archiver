"""SQLAlchemy models and database setup."""

from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    String,
    create_engine,
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
    is_newsletter = Column(Boolean, default=True)
    auto_fetch = Column(Boolean, default=True)
    priority = Column(Integer, default=0)  # higher = more important
    first_seen = Column(DateTime, default=lambda: datetime.now(UTC))

    def __repr__(self) -> str:
        return f"<Sender {self.email}>"


def get_engine(db_url: str):
    return create_engine(db_url, echo=False)


def create_tables(db_url: str) -> None:
    """Create all tables if they don't exist."""
    engine = get_engine(db_url)
    Base.metadata.create_all(engine)


def get_session(db_url: str) -> Session:
    """Get a new database session."""
    engine = get_engine(db_url)
    return sessionmaker(bind=engine)()
