"""Parse email messages and detect newsletters."""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class ParsedEmail:
    message_id: str
    subject: str
    sender_email: str
    sender_name: str
    received_date: datetime
    html_body: str
    text_body: str
    is_newsletter: bool
    headers: dict


def parse_message(message: dict) -> ParsedEmail:
    """Parse a Microsoft Graph API message dict into a ParsedEmail.

    Args:
        message: A message dict from the Graph API response.

    Returns:
        ParsedEmail with extracted fields.
    """
    from_field = message.get("from", {}).get("emailAddress", {})
    sender_email = from_field.get("address", "")
    sender_name = from_field.get("name", "")

    body = message.get("body", {})
    html_body = body.get("content", "") if body.get("contentType") == "html" else ""
    text_body = body.get("content", "") if body.get("contentType") == "text" else ""

    # Parse received date
    received_str = message.get("receivedDateTime", "")
    try:
        received_date = datetime.fromisoformat(received_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        received_date = datetime.utcnow()

    # Extract headers into a dict
    raw_headers = message.get("internetMessageHeaders", []) or []
    headers = {h["name"]: h["value"] for h in raw_headers}

    subject = message.get("subject", "(No Subject)") or "(No Subject)"
    is_newsletter = _detect_newsletter(sender_email, html_body, headers, subject)

    return ParsedEmail(
        message_id=message.get("id", ""),
        subject=message.get("subject", "(No Subject)") or "(No Subject)",
        sender_email=sender_email,
        sender_name=sender_name,
        received_date=received_date,
        html_body=html_body,
        text_body=text_body,
        is_newsletter=is_newsletter,
        headers=headers,
    )


def _is_transactional_subject(subject: str) -> bool:
    """Check if the subject line looks like a transactional email."""
    subject_lower = subject.lower()
    transactional_patterns = [
        "your receipt",
        "your order",
        "order confirmation",
        "payment confirmation",
        "payment received",
        "confirm your",
        "verify your",
        "password reset",
        "reset your password",
        "your invoice",
        "invoice for",
        "your account",
        "account update",
        "sign in",
        "log in",
        "shipping confirmation",
        "delivery confirmation",
        "has shipped",
        "welcome to",
        "thank you for your purchase",
        "subscription confirmed",
        "renewal confirmation",
    ]
    return any(pattern in subject_lower for pattern in transactional_patterns)


def _detect_newsletter(sender_email: str, html_body: str, headers: dict, subject: str = "") -> bool:
    """Heuristic to determine if a message is a newsletter.

    Checks for:
    - Transactional subject patterns (negative signal)
    - List-Unsubscribe header
    - Common newsletter sender patterns
    - Unsubscribe links in body
    """
    # Reject transactional emails by subject
    if _is_transactional_subject(subject):
        return False

    # Check List-Unsubscribe header
    if "List-Unsubscribe" in headers:
        return True

    # Check body for unsubscribe indicators
    body_lower = html_body.lower()
    unsubscribe_indicators = [
        "unsubscribe",
        "email preferences",
        "manage your subscription",
        "opt out",
        "update your preferences",
    ]

    indicator_count = sum(
        1 for ind in unsubscribe_indicators if ind in body_lower
    )

    # Common newsletter platform domains
    newsletter_domains = [
        "substack.com",
        "beehiiv.com",
        "convertkit.com",
        "mailchimp.com",
        "buttondown.email",
        "revue.email",
        "ghost.io",
        "sendfox.com",
    ]

    email_lower = sender_email.lower()
    from_newsletter_platform = any(
        domain in email_lower for domain in newsletter_domains
    )

    # Score-based: 2+ indicators or from known platform
    return indicator_count >= 2 or from_newsletter_platform
