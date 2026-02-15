"""SQLite CRUD operations for newsletters and senders."""

from datetime import datetime
from typing import Optional

from sqlalchemy import func, select

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

    # --- Newsletter operations ---

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
        """Insert a newsletter record."""
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

    def get_newsletter_count(self) -> int:
        session = self._session()
        try:
            return session.execute(select(func.count(Newsletter.id))).scalar() or 0
        finally:
            session.close()

    # --- Sender operations ---

    def get_sender(self, email: str) -> Optional[Sender]:
        """Get a sender by email, or None if not found."""
        session = self._session()
        try:
            return session.execute(
                select(Sender).where(Sender.email == email)
            ).scalar_one_or_none()
        finally:
            session.close()

    def upsert_sender(
        self,
        email: str,
        name: str = "",
        status: str = "pending",
        sample_subject: str = "",
    ) -> Sender:
        """Insert sender if not exists, otherwise return existing."""
        session = self._session()
        try:
            sender = session.execute(
                select(Sender).where(Sender.email == email)
            ).scalar_one_or_none()

            if sender is None:
                sender = Sender(
                    email=email,
                    name=name,
                    status=status,
                    sample_subject=sample_subject,
                )
                session.add(sender)
                session.commit()
                session.refresh(sender)
            else:
                changed = False
                if name and not sender.name:
                    sender.name = name
                    changed = True
                if sample_subject and not sender.sample_subject:
                    sender.sample_subject = sample_subject
                    changed = True
                if changed:
                    session.commit()
                    session.refresh(sender)

            return sender
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def set_sender_status(self, email: str, status: str) -> Optional[Sender]:
        """Update a sender's status (approved/denied/pending)."""
        session = self._session()
        try:
            sender = session.execute(
                select(Sender).where(Sender.email == email)
            ).scalar_one_or_none()
            if sender:
                sender.status = status
                session.commit()
                session.refresh(sender)
            return sender
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def get_senders_by_status(self, status: str) -> list[Sender]:
        """Get all senders with a given status."""
        session = self._session()
        try:
            results = session.execute(
                select(Sender)
                .where(Sender.status == status)
                .order_by(Sender.first_seen.desc())
            ).scalars().all()
            return list(results)
        finally:
            session.close()

    def get_approved_sender_emails(self) -> set[str]:
        """Get set of approved sender emails for fast lookup."""
        session = self._session()
        try:
            results = session.execute(
                select(Sender.email).where(Sender.status == "approved")
            ).scalars().all()
            return set(results)
        finally:
            session.close()

    def get_all_senders(self) -> list[Sender]:
        """Get all senders ordered by status then name."""
        session = self._session()
        try:
            results = session.execute(
                select(Sender).order_by(Sender.status, Sender.email)
            ).scalars().all()
            return list(results)
        finally:
            session.close()

    def get_sender_count(self) -> int:
        session = self._session()
        try:
            return session.execute(select(func.count(Sender.id))).scalar() or 0
        finally:
            session.close()
