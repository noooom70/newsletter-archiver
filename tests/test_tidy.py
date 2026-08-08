"""Tests for the inbox tidy feature (mark read + move to Archive)."""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from newsletter_archiver.core.exceptions import FetchError
from newsletter_archiver.fetcher.graph_client import GraphClient
from newsletter_archiver.fetcher.tidy import tidy_newsletter
from newsletter_archiver.storage.db_manager import DatabaseManager


@pytest.fixture
def client():
    with patch.object(GraphClient, "_get_token", return_value="fake-token"):
        c = GraphClient()
        c._token = "fake-token"
        yield c


@pytest.fixture
def db(settings):
    settings.ensure_dirs()
    return DatabaseManager(db_url=f"sqlite:///{settings.db_path}")


def _save(db, message_id="msg-1", internet_message_id="<abc@mail>"):
    return db.save_newsletter(
        message_id=message_id,
        subject="Test",
        sender_email="a@b.com",
        sender_name="A",
        received_date=datetime(2026, 8, 1, tzinfo=UTC),
        markdown_path="/tmp/x.md",
        html_path="/tmp/x.html",
        internet_message_id=internet_message_id,
    )


def _mock_response(status_code, json_data=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.ok = 200 <= status_code < 300
    resp.json.return_value = json_data or {}
    resp.content = b"x" if json_data is not None else b""
    resp.text = ""
    resp.headers = {}
    return resp


class TestGraphMethods:
    def test_mark_read_sends_patch(self, client):
        resp = _mock_response(200, {})
        with patch("newsletter_archiver.fetcher.graph_client.requests.request",
                   return_value=resp) as mock_req:
            client.mark_read("m1")
            method, url = mock_req.call_args[0][:2]
            assert method == "patch"
            assert url.endswith("/me/messages/m1")
            assert mock_req.call_args[1]["json"] == {"isRead": True}

    def test_archive_message_returns_new_id(self, client):
        resp = _mock_response(201, {"id": "new-id"})
        with patch("newsletter_archiver.fetcher.graph_client.requests.request",
                   return_value=resp) as mock_req:
            new_id = client.archive_message("m1")
            assert new_id == "new-id"
            method, url = mock_req.call_args[0][:2]
            assert method == "post"
            assert url.endswith("/me/messages/m1/move")
            assert mock_req.call_args[1]["json"] == {"destinationId": "archive"}

    def test_get_message_returns_none_on_404(self, client):
        resp = _mock_response(404, {"error": "gone"})
        with patch("newsletter_archiver.fetcher.graph_client.requests.request",
                   return_value=resp):
            assert client.get_message("m1") is None


class TestTidyNewsletter:
    def test_success_updates_ids_and_timestamp(self, client, db):
        nl = _save(db)
        with patch.object(client, "mark_read"), \
             patch.object(client, "archive_message", return_value="moved-id"):
            assert tidy_newsletter(client, db, nl.id, "msg-1", "<abc@mail>") is True

        assert db.get_untidied_newsletters() == []
        assert db.newsletter_exists("moved-id") is True

    def test_404_counts_as_done(self, client, db):
        nl = _save(db)
        with patch.object(client, "mark_read",
                          side_effect=FetchError("gone", status_code=404)):
            assert tidy_newsletter(client, db, nl.id, "msg-1") is True
        assert db.get_untidied_newsletters() == []

    def test_failure_is_nonfatal_and_retried_later(self, client, db):
        nl = _save(db)
        with patch.object(client, "mark_read",
                          side_effect=FetchError("throttled", status_code=429)):
            assert tidy_newsletter(client, db, nl.id, "msg-1") is False
        assert len(db.get_untidied_newsletters()) == 1


class TestDedup:
    def test_newsletter_exists_by_internet_message_id(self, db):
        _save(db, message_id="old-graph-id", internet_message_id="<stable@mail>")
        # After a mailbox move the Graph ID changes but the RFC ID does not
        assert db.newsletter_exists("brand-new-graph-id", "<stable@mail>", "a@b.com") is True
        assert db.newsletter_exists("brand-new-graph-id", "<other@mail>", "a@b.com") is False
        assert db.newsletter_exists("old-graph-id") is True

    def test_internet_message_id_match_is_scoped_to_sender(self, db):
        _save(db, message_id="old-graph-id", internet_message_id="<stable@mail>")
        # A different sender reusing the Message-ID must NOT count as a dupe
        assert db.newsletter_exists("new-id", "<stable@mail>", "evil@spoof.com") is False
        # Without a sender the header is ignored entirely
        assert db.newsletter_exists("new-id", "<stable@mail>") is False

    def test_migration_adds_columns(self, db):
        from sqlalchemy import inspect

        from newsletter_archiver.core.database import get_engine

        inspector = inspect(get_engine(db.db_url))
        newsletter_cols = {c["name"] for c in inspector.get_columns("newsletters")}
        assert {"internet_message_id", "tidied_at"} <= newsletter_cols
        pending_cols = {c["name"] for c in inspector.get_columns("pending_emails")}
        assert "internet_message_id" in pending_cols
