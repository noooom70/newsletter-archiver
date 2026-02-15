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
    # Patch get_settings to return our test settings
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
    assert db.get_sender_count() == 1

    # Upsert again should not duplicate
    sender2 = db.upsert_sender(email="test@example.com")
    assert db.get_sender_count() == 1
    assert sender2.name == "Test Sender"  # name preserved
