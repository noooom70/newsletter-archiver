"""Tests for the fetch command's archive/queue/skip routing logic."""

import pytest

import newsletter_archiver.cli.commands.fetch as fetch_cmd
from newsletter_archiver.storage.db_manager import DatabaseManager


class FakeIndexer:
    """Stands in for SearchIndexer so tests don't touch FTS or embeddings."""

    instances = []

    def __init__(self, db=None):
        self.indexed = []
        self.saves = 0
        FakeIndexer.instances.append(self)

    def index_newsletter(self, **kwargs):
        self.indexed.append(kwargs)

    def save_vector(self):
        self.saves += 1


@pytest.fixture
def db(wired_settings, monkeypatch):
    monkeypatch.setattr(fetch_cmd, "SearchIndexer", FakeIndexer)
    FakeIndexer.instances = []
    return DatabaseManager()


def _message(msg_id="m1", subject="Weekly Digest", email="news@example.com",
             name="Example News", html="<p>Hello</p>", headers=None):
    return {
        "id": msg_id,
        "subject": subject,
        "from": {"emailAddress": {"address": email, "name": name}},
        "receivedDateTime": "2026-07-01T12:00:00Z",
        "body": {"contentType": "html", "content": html},
        "internetMessageHeaders": headers or [],
    }


def _approve(db, email, mode):
    db.upsert_sender(email, status="approved")
    db.set_sender_mode(email, mode)


def test_auto_sender_is_archived_and_indexed(db):
    _approve(db, "news@example.com", "auto")

    fetch_cmd._archive_approved([_message()], db, {"news@example.com"})

    assert db.get_newsletter_count() == 1
    assert db.get_pending_emails() == []
    indexer = FakeIndexer.instances[0]
    assert len(indexer.indexed) == 1
    assert indexer.saves == 1


def test_review_sender_is_queued(db):
    _approve(db, "news@example.com", "review")

    fetch_cmd._archive_approved([_message()], db, {"news@example.com"})

    assert db.get_newsletter_count() == 0
    assert len(db.get_pending_emails()) == 1


def test_force_auto_overrides_review_mode(db):
    _approve(db, "news@example.com", "review")

    fetch_cmd._archive_approved([_message()], db, {"news@example.com"}, force_auto=True)

    assert db.get_newsletter_count() == 1
    assert db.get_pending_emails() == []


def test_transactional_subject_is_skipped(db):
    _approve(db, "news@example.com", "auto")

    fetch_cmd._archive_approved(
        [_message(subject="Your receipt for July")], db, {"news@example.com"}
    )

    assert db.get_newsletter_count() == 0
    assert db.get_pending_emails() == []


def test_already_archived_message_is_not_duplicated(db):
    _approve(db, "news@example.com", "auto")

    fetch_cmd._archive_approved([_message()], db, {"news@example.com"})
    fetch_cmd._archive_approved([_message()], db, {"news@example.com"})

    assert db.get_newsletter_count() == 1


def test_unapproved_newsletter_sender_becomes_pending(db):
    _approve(db, "news@example.com", "auto")
    unknown = _message(
        msg_id="m2",
        email="writer@substack.com",
        name="Some Writer",
        headers=[{"name": "List-Unsubscribe", "value": "<mailto:x>"}],
    )

    fetch_cmd._archive_approved([unknown], db, {"news@example.com"})

    sender = db.get_sender("writer@substack.com")
    assert sender is not None
    assert sender.status == "pending"
    assert db.get_newsletter_count() == 0
    assert db.get_pending_emails() == []


def test_archived_files_written_to_archive_dir(db, wired_settings):
    _approve(db, "news@example.com", "auto")

    fetch_cmd._archive_approved([_message()], db, {"news@example.com"})

    nl = db.get_all_newsletters()[0]
    md_files = list(wired_settings.archives_dir.rglob("*.md"))
    html_files = list(wired_settings.archives_dir.rglob("*.html"))
    assert len(md_files) == 1
    assert len(html_files) == 1
    assert nl.markdown_path == str(md_files[0])
