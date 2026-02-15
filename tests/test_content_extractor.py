"""Tests for HTML cleanup, Markdown conversion, and newsletter detection."""

from newsletter_archiver.fetcher.content_extractor import (
    build_markdown_document,
    calculate_reading_time,
    calculate_word_count,
    clean_html,
    html_to_markdown,
)
from newsletter_archiver.fetcher.email_parser import _is_transactional_subject


def test_clean_html_removes_scripts(sample_html):
    cleaned = clean_html(sample_html)
    assert "<script>" not in cleaned
    assert "tracking" not in cleaned


def test_clean_html_removes_styles(sample_html):
    cleaned = clean_html(sample_html)
    assert "<style>" not in cleaned


def test_clean_html_removes_tracking_pixels(sample_html):
    cleaned = clean_html(sample_html)
    assert 'width="1"' not in cleaned
    assert "pixel.gif" not in cleaned


def test_clean_html_removes_unsubscribe_links(sample_html):
    cleaned = clean_html(sample_html)
    assert "Unsubscribe" not in cleaned


def test_html_to_markdown_preserves_content(sample_html):
    md = html_to_markdown(sample_html)
    assert "Weekly Tech Digest" in md
    assert "Rust Memory Safety" in md
    assert "memory bugs" in md


def test_html_to_markdown_removes_noise(sample_html):
    md = html_to_markdown(sample_html)
    assert "pixel.gif" not in md
    assert "<script>" not in md


def test_build_markdown_document():
    doc = build_markdown_document(
        subject="Test Newsletter",
        sender_name="Test Author",
        sender_email="test@example.com",
        received_date="2025-01-15T10:00:00",
        markdown_body="# Hello\n\nThis is a test.",
    )
    assert "title: \"Test Newsletter\"" in doc
    assert 'from: "Test Author <test@example.com>"' in doc
    assert "# Hello" in doc


def test_calculate_word_count():
    assert calculate_word_count("hello world foo bar") == 4
    assert calculate_word_count("") == 0


def test_calculate_reading_time():
    assert calculate_reading_time(200) == 1.0
    assert calculate_reading_time(500) == 2.5
    assert calculate_reading_time(0) == 0.0


def test_transactional_subject_detection():
    # Should be detected as transactional
    assert _is_transactional_subject("Your receipt from Stratechery")
    assert _is_transactional_subject("Your Order Confirmation #12345")
    assert _is_transactional_subject("Confirm your email address")
    assert _is_transactional_subject("Password Reset Request")
    assert _is_transactional_subject("Your invoice for February")
    assert _is_transactional_subject("Welcome to Our Service")

    # Should NOT be detected as transactional
    assert not _is_transactional_subject("Aggregators and AI (This Week in Stratechery)")
    assert not _is_transactional_subject("The Disappearance of Nancy Guthrie")
    assert not _is_transactional_subject("Longreads + Open Thread")
    assert not _is_transactional_subject("The World in Brief: Rubio love-bombs Europe")
