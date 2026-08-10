"""SQLite CRUD operations for newsletters and senders."""

from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Optional

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import sessionmaker

from newsletter_archiver.core.config import get_settings
from newsletter_archiver.core.database import (
    EmbeddingChunk,
    Newsletter,
    PendingEmail,
    Sender,
    create_tables,
    get_engine,
)


def _to_naive_utc(dt: datetime) -> datetime:
    """Normalize a datetime to naive UTC for storage (SQLite drops tzinfo)."""
    if dt.tzinfo is not None:
        dt = dt.astimezone(UTC).replace(tzinfo=None)
    return dt


class DatabaseManager:
    def __init__(self, db_url: Optional[str] = None):
        self.db_url = db_url or get_settings().db_url
        create_tables(self.db_url)
        # expire_on_commit=False so returned objects stay usable after the
        # session closes (they are detached but fully loaded).
        self._sessionmaker = sessionmaker(
            bind=get_engine(self.db_url), expire_on_commit=False
        )

    @contextmanager
    def _session(self):
        session = self._sessionmaker()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    # --- Newsletter operations ---

    def newsletter_exists(
        self,
        message_id: str,
        internet_message_id: str = "",
        sender_email: str = "",
    ) -> bool:
        """Check if a newsletter is already stored.

        Matches on the Graph message_id or, when both are provided, the RFC
        internet_message_id — the latter survives mailbox moves, which
        change Graph message IDs. The internet_message_id match is scoped to
        the same sender: the header is sender-controlled, so an unscoped
        match would let one sender reuse another's Message-ID to have their
        email silently skipped as a duplicate.
        """
        conditions = [Newsletter.message_id == message_id]
        if internet_message_id and sender_email:
            conditions.append(and_(
                Newsletter.internet_message_id == internet_message_id,
                Newsletter.sender_email == sender_email,
            ))
        with self._session() as session:
            result = session.execute(
                select(Newsletter.id).where(or_(*conditions))
            ).first()
            return result is not None

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
        internet_message_id: str = "",
    ) -> Newsletter:
        """Insert a newsletter record."""
        with self._session() as session:
            newsletter = Newsletter(
                message_id=message_id,
                internet_message_id=internet_message_id,
                subject=subject,
                sender_email=sender_email,
                sender_name=sender_name,
                received_date=_to_naive_utc(received_date),
                markdown_path=markdown_path,
                html_path=html_path,
                word_count=word_count,
                reading_time_minutes=reading_time_minutes,
                tags=tags,
                category=category,
            )
            session.add(newsletter)
            return newsletter

    def mark_newsletter_tidied(
        self,
        newsletter_id: int,
        new_message_id: str = "",
        internet_message_id: str = "",
    ) -> None:
        """Record that a newsletter's email was marked read + archived.

        Updates the stored Graph message_id when the move produced a new one,
        and backfills internet_message_id when available.
        """
        with self._session() as session:
            newsletter = session.get(Newsletter, newsletter_id)
            if newsletter is None:
                return
            if new_message_id:
                newsletter.message_id = new_message_id
            if internet_message_id:
                newsletter.internet_message_id = internet_message_id
            newsletter.tidied_at = _to_naive_utc(datetime.now(UTC))

    def get_untidied_newsletters(self) -> list[Newsletter]:
        """Newsletters whose emails have not yet been marked read + archived."""
        with self._session() as session:
            return list(session.execute(
                select(Newsletter).where(Newsletter.tidied_at.is_(None))
                .order_by(Newsletter.received_date)
            ).scalars())

    def get_newsletter_count(self) -> int:
        with self._session() as session:
            return session.execute(select(func.count(Newsletter.id))).scalar() or 0

    def get_latest_received_date(self) -> Optional[datetime]:
        """Get the most recent received_date across all archived newsletters.

        Returned as an aware UTC datetime (stored naive UTC in SQLite).
        """
        with self._session() as session:
            latest = session.execute(
                select(func.max(Newsletter.received_date))
            ).scalar()
            if latest is not None and latest.tzinfo is None:
                latest = latest.replace(tzinfo=UTC)
            return latest

    # --- Sender operations ---

    def get_sender(self, email: str) -> Optional[Sender]:
        """Get a sender by email, or None if not found."""
        with self._session() as session:
            return session.execute(
                select(Sender).where(Sender.email == email)
            ).scalar_one_or_none()

    def upsert_sender(
        self,
        email: str,
        name: str = "",
        status: str = "pending",
        sample_subject: str = "",
    ) -> Sender:
        """Insert sender if not exists, otherwise return existing."""
        with self._session() as session:
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
            else:
                if name and not sender.name:
                    sender.name = name
                if sample_subject and not sender.sample_subject:
                    sender.sample_subject = sample_subject

            return sender

    def set_sender_status(self, email: str, status: str) -> Optional[Sender]:
        """Update a sender's status (approved/denied/pending)."""
        with self._session() as session:
            sender = session.execute(
                select(Sender).where(Sender.email == email)
            ).scalar_one_or_none()
            if sender:
                sender.status = status
            return sender

    def get_senders_by_status(self, status: str) -> list[Sender]:
        """Get all senders with a given status."""
        with self._session() as session:
            results = session.execute(
                select(Sender)
                .where(Sender.status == status)
                .order_by(Sender.first_seen.desc())
            ).scalars().all()
            return list(results)

    def get_approved_sender_emails(self) -> set[str]:
        """Get set of approved sender emails for fast lookup."""
        with self._session() as session:
            results = session.execute(
                select(Sender.email).where(Sender.status == "approved")
            ).scalars().all()
            return set(results)

    def get_all_senders(self) -> list[Sender]:
        """Get all senders ordered by status then name."""
        with self._session() as session:
            results = session.execute(
                select(Sender).order_by(Sender.status, Sender.email)
            ).scalars().all()
            return list(results)

    def get_sender_count(self) -> int:
        with self._session() as session:
            return session.execute(select(func.count(Sender.id))).scalar() or 0

    def set_sender_mode(self, email: str, mode: str) -> Optional[Sender]:
        """Update a sender's archive mode (auto/review)."""
        with self._session() as session:
            sender = session.execute(
                select(Sender).where(Sender.email == email)
            ).scalar_one_or_none()
            if sender:
                sender.mode = mode
            return sender

    def get_senders_by_mode(self, mode: str) -> list[Sender]:
        """Get all approved senders with a given mode."""
        with self._session() as session:
            results = session.execute(
                select(Sender)
                .where(Sender.status == "approved", Sender.mode == mode)
                .order_by(Sender.email)
            ).scalars().all()
            return list(results)

    # --- Newsletter query operations ---

    def get_all_newsletters(self) -> list[Newsletter]:
        """Get all newsletters ordered by received date."""
        with self._session() as session:
            results = session.execute(
                select(Newsletter).order_by(Newsletter.received_date.desc())
            ).scalars().all()
            return list(results)

    def get_newsletter_by_id(self, newsletter_id: int) -> Optional[Newsletter]:
        """Get a newsletter by its primary key ID."""
        with self._session() as session:
            return session.execute(
                select(Newsletter).where(Newsletter.id == newsletter_id)
            ).scalar_one_or_none()

    def update_newsletter_metrics(
        self, markdown_path: str, word_count: int, reading_time_minutes: float
    ) -> bool:
        """Refresh word count metrics for all rows owning markdown_path.

        Multiple rows can share a markdown_path: a publisher double-send
        (distinct message_id/internet_message_id, both correctly passing
        dedup) archived to the same file. All matching rows are updated.

        Update-only: returns False (and writes nothing) when no row matches.
        """
        with self._session() as session:
            newsletters = session.execute(
                select(Newsletter).where(Newsletter.markdown_path == markdown_path)
            ).scalars().all()
            if not newsletters:
                return False
            for newsletter in newsletters:
                newsletter.word_count = word_count
                newsletter.reading_time_minutes = reading_time_minutes
            return True

    # --- Pending email operations ---

    def save_pending_email(
        self,
        message_id: str,
        subject: str,
        sender_email: str,
        sender_name: str,
        received_date: datetime,
        html_body: str,
        internet_message_id: str = "",
    ) -> PendingEmail:
        """Queue an email for review."""
        with self._session() as session:
            pending = PendingEmail(
                message_id=message_id,
                internet_message_id=internet_message_id,
                subject=subject,
                sender_email=sender_email,
                sender_name=sender_name,
                received_date=_to_naive_utc(received_date),
                html_body=html_body,
            )
            session.add(pending)
            return pending

    def pending_email_exists(self, message_id: str) -> bool:
        """Check if a pending email with this message_id already exists."""
        with self._session() as session:
            result = session.execute(
                select(PendingEmail).where(PendingEmail.message_id == message_id)
            ).scalar_one_or_none()
            return result is not None

    def get_pending_emails(self, sender_email: Optional[str] = None) -> list[PendingEmail]:
        """List queued emails, optionally filtered by sender."""
        with self._session() as session:
            stmt = select(PendingEmail).order_by(PendingEmail.received_date.desc())
            if sender_email:
                stmt = stmt.where(PendingEmail.sender_email == sender_email)
            results = session.execute(stmt).scalars().all()
            return list(results)

    def get_pending_email(self, pending_id: int) -> Optional[PendingEmail]:
        """Get a single pending email by ID."""
        with self._session() as session:
            return session.execute(
                select(PendingEmail).where(PendingEmail.id == pending_id)
            ).scalar_one_or_none()

    def delete_pending_email(self, pending_id: int) -> bool:
        """Remove a pending email after approve/deny."""
        with self._session() as session:
            pending = session.execute(
                select(PendingEmail).where(PendingEmail.id == pending_id)
            ).scalar_one_or_none()
            if pending:
                session.delete(pending)
                return True
            return False

    # --- Embedding chunk operations ---

    def save_embedding_chunks(self, newsletter_id: int, chunks: list[str]) -> None:
        """Save text chunks for a newsletter's embeddings, replacing any existing."""
        with self._session() as session:
            existing = session.execute(
                select(EmbeddingChunk).where(EmbeddingChunk.newsletter_id == newsletter_id)
            ).scalars().all()
            for chunk in existing:
                session.delete(chunk)

            for i, text in enumerate(chunks):
                session.add(EmbeddingChunk(
                    newsletter_id=newsletter_id,
                    chunk_index=i,
                    chunk_text=text,
                ))

    def get_embedding_chunks(self, newsletter_id: int) -> list[EmbeddingChunk]:
        """Get all text chunks for a newsletter, ordered by index."""
        with self._session() as session:
            results = session.execute(
                select(EmbeddingChunk)
                .where(EmbeddingChunk.newsletter_id == newsletter_id)
                .order_by(EmbeddingChunk.chunk_index)
            ).scalars().all()
            return list(results)

    def delete_embedding_chunks(self, newsletter_id: int) -> None:
        """Delete all embedding chunks for a newsletter."""
        with self._session() as session:
            chunks = session.execute(
                select(EmbeddingChunk).where(EmbeddingChunk.newsletter_id == newsletter_id)
            ).scalars().all()
            for chunk in chunks:
                session.delete(chunk)

    def get_newsletter_ids_with_chunks(self) -> set[int]:
        """Get set of newsletter IDs that have embedding chunks stored."""
        with self._session() as session:
            results = session.execute(
                select(EmbeddingChunk.newsletter_id).distinct()
            ).scalars().all()
            return set(results)
