"""Tests for file manager and database manager."""

from datetime import datetime

from newsletter_archiver.storage.file_manager import (
    get_archive_path,
    get_sender_dirname,
    save_newsletter_files,
    slugify,
)
from newsletter_archiver.storage.db_manager import DatabaseManager


def test_slugify():
    assert slugify("Hello World!") == "hello-world"
    assert slugify("It's a test & more") == "its-a-test-more"
    assert slugify("   spaces   ") == "spaces"


def test_slugify_max_length():
    long_text = "a" * 200
    assert len(slugify(long_text, max_length=80)) == 80


def test_get_sender_dirname():
    assert get_sender_dirname("The Hustle", "team@thehustle.co") == "the-hustle"
    assert get_sender_dirname("", "newsletter@substack.com") == "newsletter"


def test_get_archive_path(settings, monkeypatch):
    import newsletter_archiver.storage.file_manager as fm
    monkeypatch.setattr(fm, "get_settings", lambda: settings)

    path = get_archive_path(
        sender_name="The Hustle",
        sender_email="team@thehustle.co",
        received_date=datetime(2025, 3, 15, 10, 0, 0),
        subject="5 Trends Reshaping Tech",
    )
    assert "2025" in str(path)
    assert "03" in str(path)
    assert "the-hustle" in str(path)
    assert "2025-03-15" in str(path)


def test_save_newsletter_files(tmp_path):
    base = tmp_path / "test_newsletter"
    md_path, html_path = save_newsletter_files(
        base_path=base,
        markdown_content="# Test",
        html_content="<h1>Test</h1>",
    )
    assert md_path.exists()
    assert html_path.exists()
    assert md_path.read_text() == "# Test"
    assert html_path.read_text() == "<h1>Test</h1>"


def test_db_manager_newsletter_crud(settings):
    settings.ensure_dirs()
    db = DatabaseManager(db_url=f"sqlite:///{settings.db_path}")

    assert db.get_newsletter_count() == 0
    assert not db.newsletter_exists("msg-001")

    db.save_newsletter(
        message_id="msg-001",
        subject="Test Newsletter",
        sender_email="test@example.com",
        sender_name="Test",
        received_date=datetime(2025, 1, 15),
        markdown_path="/tmp/test.md",
        html_path="/tmp/test.html",
        word_count=100,
        reading_time_minutes=0.5,
    )

    assert db.newsletter_exists("msg-001")
    assert db.get_newsletter_count() == 1


def test_db_manager_sender_crud(settings):
    settings.ensure_dirs()
    db = DatabaseManager(db_url=f"sqlite:///{settings.db_path}")

    sender = db.upsert_sender(email="test@example.com", name="Test Sender")
    assert sender.email == "test@example.com"
    assert sender.name == "Test Sender"
    assert sender.status == "pending"
    assert db.get_sender_count() == 1

    # Upsert again should not duplicate
    sender2 = db.upsert_sender(email="test@example.com")
    assert db.get_sender_count() == 1
    assert sender2.name == "Test Sender"


def test_db_manager_sender_approval_flow(settings):
    settings.ensure_dirs()
    db = DatabaseManager(db_url=f"sqlite:///{settings.db_path}")

    # Add as pending
    db.upsert_sender(email="news@substack.com", name="Substack", sample_subject="Weekly Digest")
    assert len(db.get_senders_by_status("pending")) == 1
    assert len(db.get_approved_sender_emails()) == 0

    # Approve
    db.set_sender_status("news@substack.com", "approved")
    assert len(db.get_senders_by_status("pending")) == 0
    assert "news@substack.com" in db.get_approved_sender_emails()

    # Deny another
    db.upsert_sender(email="spam@example.com", name="Spam")
    db.set_sender_status("spam@example.com", "denied")
    assert len(db.get_senders_by_status("denied")) == 1
    assert "spam@example.com" not in db.get_approved_sender_emails()


def test_db_manager_add_approved_directly(settings):
    settings.ensure_dirs()
    db = DatabaseManager(db_url=f"sqlite:///{settings.db_path}")

    # Manual add goes straight to approved
    db.upsert_sender(email="fav@newsletter.com", name="Favorite", status="approved")
    assert "fav@newsletter.com" in db.get_approved_sender_emails()


def test_db_manager_sender_mode(settings):
    settings.ensure_dirs()
    db = DatabaseManager(db_url=f"sqlite:///{settings.db_path}")

    # Default mode is review
    db.upsert_sender(email="test@example.com", name="Test", status="approved")
    sender = db.get_sender("test@example.com")
    assert sender.mode == "review"

    # Set to auto
    db.set_sender_mode("test@example.com", "auto")
    sender = db.get_sender("test@example.com")
    assert sender.mode == "auto"

    # get_senders_by_mode
    db.upsert_sender(email="auto@example.com", name="Auto", status="approved")
    db.set_sender_mode("auto@example.com", "auto")
    db.upsert_sender(email="review@example.com", name="Review", status="approved")

    auto_senders = db.get_senders_by_mode("auto")
    review_senders = db.get_senders_by_mode("review")
    auto_emails = {s.email for s in auto_senders}
    review_emails = {s.email for s in review_senders}
    assert "test@example.com" in auto_emails
    assert "auto@example.com" in auto_emails
    assert "review@example.com" in review_emails


def test_db_manager_pending_email_crud(settings):
    settings.ensure_dirs()
    db = DatabaseManager(db_url=f"sqlite:///{settings.db_path}")

    # No pending emails initially
    assert db.get_pending_emails() == []
    assert not db.pending_email_exists("msg-100")

    # Save a pending email
    pending = db.save_pending_email(
        message_id="msg-100",
        subject="Review This Newsletter",
        sender_email="news@example.com",
        sender_name="News",
        received_date=datetime(2025, 6, 15, 10, 0),
        html_body="<h1>Hello</h1>",
    )
    assert pending.id is not None
    assert pending.message_id == "msg-100"

    # Exists check
    assert db.pending_email_exists("msg-100")
    assert not db.pending_email_exists("msg-999")

    # List pending
    all_pending = db.get_pending_emails()
    assert len(all_pending) == 1
    assert all_pending[0].subject == "Review This Newsletter"

    # Filter by sender
    assert len(db.get_pending_emails(sender_email="news@example.com")) == 1
    assert len(db.get_pending_emails(sender_email="other@example.com")) == 0

    # Get by ID
    fetched = db.get_pending_email(pending.id)
    assert fetched is not None
    assert fetched.message_id == "msg-100"

    # Delete
    assert db.delete_pending_email(pending.id) is True
    assert db.get_pending_emails() == []
    assert not db.pending_email_exists("msg-100")

    # Delete non-existent
    assert db.delete_pending_email(999) is False


def test_db_manager_pending_email_dedup(settings):
    settings.ensure_dirs()
    db = DatabaseManager(db_url=f"sqlite:///{settings.db_path}")

    db.save_pending_email(
        message_id="msg-200",
        subject="First",
        sender_email="a@example.com",
        sender_name="A",
        received_date=datetime(2025, 6, 15),
        html_body="<p>1</p>",
    )

    # Saving same message_id should raise (unique constraint)
    import pytest
    with pytest.raises(Exception):
        db.save_pending_email(
            message_id="msg-200",
            subject="Duplicate",
            sender_email="a@example.com",
            sender_name="A",
            received_date=datetime(2025, 6, 15),
            html_body="<p>2</p>",
        )
