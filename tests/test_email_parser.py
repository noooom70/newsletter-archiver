"""Tests for email parsing and newsletter detection heuristics."""

from newsletter_archiver.fetcher.email_parser import _detect_newsletter, parse_message


def _message(**overrides):
    msg = {
        "id": "msg-1",
        "subject": "Weekly Digest",
        "from": {"emailAddress": {"address": "news@example.com", "name": "Example News"}},
        "receivedDateTime": "2026-07-01T12:00:00Z",
        "body": {"contentType": "html", "content": "<p>Hello</p>"},
        "internetMessageHeaders": [],
    }
    msg.update(overrides)
    return msg


class TestDetectNewsletter:
    def test_list_unsubscribe_header(self):
        headers = {"List-Unsubscribe": "<mailto:unsub@example.com>"}
        assert _detect_newsletter("a@b.com", "", headers, "Weekly Digest") is True

    def test_transactional_subject_rejected_despite_header(self):
        headers = {"List-Unsubscribe": "<mailto:unsub@example.com>"}
        assert _detect_newsletter("a@b.com", "", headers, "Your receipt from ACME") is False

    def test_newsletter_platform_domain(self):
        assert _detect_newsletter("writer@substack.com", "", {}, "An essay") is True

    def test_two_body_indicators(self):
        html = '<a href="#">unsubscribe</a> <a href="#">email preferences</a>'
        assert _detect_newsletter("a@b.com", html, {}, "Weekly Digest") is True

    def test_single_body_indicator_not_enough(self):
        html = '<a href="#">unsubscribe</a>'
        assert _detect_newsletter("a@b.com", html, {}, "Weekly Digest") is False

    def test_plain_email_not_newsletter(self):
        assert _detect_newsletter("friend@gmail.com", "<p>lunch?</p>", {}, "Lunch?") is False


class TestParseMessage:
    def test_fields_extracted(self):
        parsed = parse_message(_message())
        assert parsed.message_id == "msg-1"
        assert parsed.subject == "Weekly Digest"
        assert parsed.sender_email == "news@example.com"
        assert parsed.sender_name == "Example News"
        assert parsed.html_body == "<p>Hello</p>"

    def test_received_date_is_aware_utc(self):
        parsed = parse_message(_message())
        assert parsed.received_date.tzinfo is not None
        assert parsed.received_date.utcoffset().total_seconds() == 0

    def test_missing_date_falls_back_to_aware_now(self):
        parsed = parse_message(_message(receivedDateTime=""))
        assert parsed.received_date.tzinfo is not None

    def test_missing_subject_gets_placeholder(self):
        parsed = parse_message(_message(subject=None))
        assert parsed.subject == "(No Subject)"
