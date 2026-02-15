"""SQLite CRUD operations for newsletters and senders."""

from datetime import datetime
from typing import Optional

from sqlalchemy import select

from newsletter_archiver.core.config import get_settings
from newsletter_archiver.core.database import (
    Newsletter,
    Sender,
    create_tables,
    get_session,
)


class DatabaseManager:
    def __init__(self, db_url: Optional[str] = None):
        self.db_url = db_url or get_settings().db_url
        create_tables(self.db_url)

    def _session(self):
        return get_session(self.db_url)

    def newsletter_exists(self, message_id: str) -> bool:
        """Check if a newsletter with this message_id is already stored."""
        session = self._session()
        try:
            result = session.execute(
                select(Newsletter).where(Newsletter.message_id == message_id)
            ).scalar_one_or_none()
            return result is not None
        finally:
            session.close()

    def save_newsletter(
        self,
        message_id: str,
        subject: str,
        sender_email: str,
        sender_name: str,
        received_date: datetime,
        markdown_path: str,
        html_path: str,
        word_count: int = 0,
        reading_time_minutes: float = 0.0,
        tags: str = "",
        category: str = "",
    ) -> Newsletter:
        """Insert a newsletter record. Returns the created Newsletter."""
        session = self._session()
        try:
            newsletter = Newsletter(
                message_id=message_id,
                subject=subject,
                sender_email=sender_email,
                sender_name=sender_name,
                received_date=received_date,
                markdown_path=markdown_path,
                html_path=html_path,
                word_count=word_count,
                reading_time_minutes=reading_time_minutes,
                tags=tags,
                category=category,
            )
            session.add(newsletter)
            session.commit()
            session.refresh(newsletter)
            return newsletter
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def upsert_sender(self, email: str, name: str = "") -> Sender:
        """Insert sender if not exists, otherwise return existing."""
        session = self._session()
        try:
            sender = session.execute(
                select(Sender).where(Sender.email == email)
            ).scalar_one_or_none()

            if sender is None:
                sender = Sender(email=email, name=name)
                session.add(sender)
                session.commit()
                session.refresh(sender)
            elif name and not sender.name:
                sender.name = name
                session.commit()
                session.refresh(sender)

            return sender
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def get_allowed_senders(self) -> list[str]:
        """Get list of sender emails marked as newsletters with auto_fetch."""
        session = self._session()
        try:
            results = session.execute(
                select(Sender.email).where(
                    Sender.is_newsletter == True,  # noqa: E712
                    Sender.auto_fetch == True,  # noqa: E712
                )
            ).scalars().all()
            return list(results)
        finally:
            session.close()

    def get_newsletter_count(self) -> int:
        """Get total number of archived newsletters."""
        session = self._session()
        try:
            from sqlalchemy import func
            result = session.execute(
                select(func.count(Newsletter.id))
            ).scalar()
            return result or 0
        finally:
            session.close()

    def get_sender_count(self) -> int:
        """Get total number of known senders."""
        session = self._session()
        try:
            from sqlalchemy import func
            result = session.execute(
                select(func.count(Sender.id))
            ).scalar()
            return result or 0
        finally:
            session.close()
