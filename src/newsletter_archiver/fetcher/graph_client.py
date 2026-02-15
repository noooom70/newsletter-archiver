"""Microsoft Graph API authentication and email fetching via O365."""

from datetime import datetime, timedelta
from typing import Optional

from O365 import Account, FileSystemTokenBackend

from newsletter_archiver.core.config import get_settings
from newsletter_archiver.core.exceptions import AuthError, FetchError


class GraphClient:
    def __init__(self):
        self.settings = get_settings()
        self._account: Optional[Account] = None

    def _get_account(self) -> Account:
        if self._account is not None:
            return self._account

        if not self.settings.is_configured:
            raise AuthError(
                "Azure AD credentials not configured. "
                "Run: newsletter-archiver config setup"
            )

        credentials = (
            self.settings.azure_client_id,
            self.settings.azure_client_secret,
        )

        token_backend = FileSystemTokenBackend(
            token_path=str(self.settings.archive_dir),
            token_filename="o365_token.txt",
        )

        self._account = Account(
            credentials,
            token_backend=token_backend,
            auth_flow_type="authorization",
        )

        if not self._account.is_authenticated:
            if not self._account.authenticate(
                scopes=["basic", "message_all"]
            ):
                raise AuthError(
                    "Failed to authenticate with Microsoft Graph. "
                    "Please check your Azure AD credentials."
                )

        return self._account

    def authenticate(self) -> bool:
        """Run interactive authentication flow. Returns True on success."""
        try:
            self._get_account()
            return True
        except AuthError:
            raise
        except Exception as e:
            raise AuthError(f"Authentication failed: {e}") from e

    def fetch_emails(
        self,
        days_back: int = 7,
        sender_filter: Optional[str] = None,
        batch_size: Optional[int] = None,
    ) -> list:
        """Fetch emails from Outlook inbox.

        Args:
            days_back: Number of days back to fetch.
            sender_filter: Optional sender email/domain to filter by.
            batch_size: Number of emails per page.

        Returns:
            List of O365 Message objects.
        """
        account = self._get_account()
        mailbox = account.mailbox()
        inbox = mailbox.inbox_folder()

        since = datetime.utcnow() - timedelta(days=days_back)

        query = inbox.new_query().on_attribute("receivedDateTime").greater_equal(since)

        if sender_filter:
            query = query.chain("and").on_attribute("from/emailAddress/address").contains(sender_filter)

        try:
            messages = []
            batch = batch_size or self.settings.batch_size
            for message in inbox.get_messages(
                limit=batch,
                query=query,
                order_by="receivedDateTime desc",
                download_attachments=False,
            ):
                messages.append(message)

            return messages
        except Exception as e:
            raise FetchError(f"Failed to fetch emails: {e}") from e
