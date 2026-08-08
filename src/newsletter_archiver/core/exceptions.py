"""Custom exceptions for newsletter archiver."""


class NewsletterArchiverError(Exception):
    """Base exception for all newsletter archiver errors."""


class ConfigError(NewsletterArchiverError):
    """Configuration is missing or invalid."""


class AuthError(NewsletterArchiverError):
    """Authentication with Microsoft Graph failed."""


class FetchError(NewsletterArchiverError):
    """A Microsoft Graph mail request failed."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class ParseError(NewsletterArchiverError):
    """Failed to parse email content."""


class StorageError(NewsletterArchiverError):
    """Failed to store newsletter to disk or database."""
