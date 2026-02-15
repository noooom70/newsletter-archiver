"""Microsoft Graph API authentication and email fetching via MSAL + REST."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Optional

import msal
import requests

from newsletter_archiver.core.config import get_settings
from newsletter_archiver.core.exceptions import AuthError, FetchError

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
SCOPES = ["Mail.Read"]


class GraphClient:
    def __init__(self):
        self.settings = get_settings()
        self._app: Optional[msal.PublicClientApplication] = None
        self._token: Optional[str] = None

    def _get_app(self) -> msal.PublicClientApplication:
        if self._app is not None:
            return self._app

        cache = msal.SerializableTokenCache()
        cache_path = self.settings.token_path
        if cache_path.exists():
            cache.deserialize(cache_path.read_text())

        self._app = msal.PublicClientApplication(
            client_id=self.settings.azure_client_id,
            authority="https://login.microsoftonline.com/consumers",
            token_cache=cache,
        )
        return self._app

    def _save_cache(self) -> None:
        app = self._get_app()
        cache = app.token_cache
        if cache.has_state_changed:
            self.settings.token_path.write_text(cache.serialize())

    def _get_token(self) -> str:
        """Get a valid access token, using cache or device code flow."""
        if self._token:
            return self._token

        app = self._get_app()

        # Try silent auth first (cached refresh token)
        accounts = app.get_accounts()
        if accounts:
            result = app.acquire_token_silent(SCOPES, account=accounts[0])
            if result and "access_token" in result:
                self._save_cache()
                self._token = result["access_token"]
                return self._token

        # Fall back to device code flow
        flow = app.initiate_device_flow(scopes=SCOPES)
        if "user_code" not in flow:
            raise AuthError(f"Failed to start device flow: {flow.get('error_description', 'unknown error')}")

        print()
        print(f"  To sign in, open: {flow['verification_uri']}")
        print(f"  Enter code:       {flow['user_code']}")
        print()

        result = app.acquire_token_by_device_flow(flow)

        if "access_token" not in result:
            error = result.get("error_description", result.get("error", "unknown"))
            raise AuthError(f"Authentication failed: {error}")

        self._save_cache()
        self._token = result["access_token"]
        return self._token

    def authenticate(self) -> bool:
        """Run authentication flow. Returns True on success."""
        try:
            self._get_token()
            return True
        except AuthError:
            raise
        except Exception as e:
            raise AuthError(f"Authentication failed: {e}") from e

    def _graph_get(self, endpoint: str, params: Optional[dict] = None) -> dict:
        """Make an authenticated GET request to Microsoft Graph."""
        token = self._get_token()
        headers = {"Authorization": f"Bearer {token}"}
        resp = requests.get(f"{GRAPH_BASE}{endpoint}", headers=headers, params=params)

        if resp.status_code == 401:
            # Token might have expired mid-session, clear and retry
            self._token = None
            token = self._get_token()
            headers = {"Authorization": f"Bearer {token}"}
            resp = requests.get(f"{GRAPH_BASE}{endpoint}", headers=headers, params=params)

        if not resp.ok:
            raise FetchError(f"Graph API error {resp.status_code}: {resp.text}")

        return resp.json()

    def fetch_emails(
        self,
        days_back: int = 7,
        sender_filter: Optional[str] = None,
        batch_size: Optional[int] = None,
    ) -> list[dict]:
        """Fetch emails from Outlook inbox via Graph API.

        Returns list of message dicts from the Graph API.
        """
        since = (datetime.now(UTC) - timedelta(days=days_back)).strftime("%Y-%m-%dT%H:%M:%SZ")

        filter_parts = [f"receivedDateTime ge {since}"]
        if sender_filter:
            filter_parts.append(
                f"contains(from/emailAddress/address, '{sender_filter}')"
            )

        params = {
            "$filter": " and ".join(filter_parts),
            "$orderby": "receivedDateTime desc",
            "$top": str(batch_size or self.settings.batch_size),
            "$select": "id,subject,from,receivedDateTime,body,internetMessageHeaders",
        }

        try:
            messages = []
            data = self._graph_get("/me/messages", params=params)
            messages.extend(data.get("value", []))

            # Handle pagination
            while "@odata.nextLink" in data:
                next_url = data["@odata.nextLink"]
                token = self._get_token()
                resp = requests.get(
                    next_url,
                    headers={"Authorization": f"Bearer {token}"},
                )
                if not resp.ok:
                    break
                data = resp.json()
                messages.extend(data.get("value", []))

            return messages
        except FetchError:
            raise
        except Exception as e:
            raise FetchError(f"Failed to fetch emails: {e}") from e
