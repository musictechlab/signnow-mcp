"""Standalone SignNow API client using httpx."""

import logging
import os
import sys
import time

import httpx

logger = logging.getLogger(__name__)

TOKEN_TTL_BUFFER = 300  # Refresh 5 min before expiry


class SignNowClient:
    """REST client for the airSlate SignNow API."""

    def __init__(
        self,
        base_url: str | None = None,
        basic_auth: str | None = None,
        username: str | None = None,
        password: str | None = None,
    ):
        self.base_url = (
            base_url or os.getenv("SIGNNOW_API_BASE_URL", "")
        ).rstrip("/")
        self.basic_auth = basic_auth or os.getenv("SIGNNOW_BASIC_AUTH", "")
        self.username = username or os.getenv("SIGNNOW_USERNAME", "")
        self.password = password or os.getenv("SIGNNOW_PASSWORD", "")

        if not all([self.base_url, self.basic_auth, self.username, self.password]):
            print(
                "ERROR: SignNow not fully configured.\n"
                "Required env vars: SIGNNOW_API_BASE_URL, SIGNNOW_BASIC_AUTH, "
                "SIGNNOW_USERNAME, SIGNNOW_PASSWORD\n"
                "See .env.example for details.",
                file=sys.stderr,
            )
            raise ValueError("Missing required SignNow configuration")

        self._token: str | None = None
        self._token_expires_at: float = 0

    def _get_access_token(self) -> str:
        """Get a valid access token, refreshing if needed."""
        if self._token and time.time() < self._token_expires_at:
            return self._token

        with httpx.Client(timeout=30.0) as http:
            resp = http.post(
                f"{self.base_url}/oauth2/token",
                data={
                    "grant_type": "password",
                    "username": self.username,
                    "password": self.password,
                    "scope": "*",
                },
                headers={
                    "Authorization": f"Basic {self.basic_auth}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
            )
            resp.raise_for_status()
            data = resp.json()

        self._token = data["access_token"]
        expires_in = data.get("expires_in", 3600)
        self._token_expires_at = time.time() + expires_in - TOKEN_TTL_BUFFER
        logger.info("SignNow access token obtained")
        return self._token

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._get_access_token()}"}

    # --- Document operations ---

    def upload_document(self, pdf_bytes: bytes, filename: str) -> dict:
        """Upload a PDF to SignNow. Returns {"id": "document_id"}."""
        with httpx.Client(timeout=60.0) as http:
            resp = http.post(
                f"{self.base_url}/document",
                headers=self._auth_headers(),
                files={"file": (filename, pdf_bytes, "application/pdf")},
            )
            resp.raise_for_status()
            return resp.json()

    def get_document(self, document_id: str) -> dict:
        """Get document details including status, roles, and fields."""
        with httpx.Client(timeout=30.0) as http:
            resp = http.get(
                f"{self.base_url}/document/{document_id}",
                headers=self._auth_headers(),
            )
            resp.raise_for_status()
            return resp.json()

    def list_documents(self) -> list[dict]:
        """List all documents in the account."""
        with httpx.Client(timeout=30.0) as http:
            resp = http.get(
                f"{self.base_url}/user/documentsv2",
                headers=self._auth_headers(),
            )
            resp.raise_for_status()
            return resp.json()

    def download_document(self, document_id: str) -> bytes:
        """Download the signed (collapsed) PDF as bytes."""
        with httpx.Client(timeout=60.0) as http:
            resp = http.get(
                f"{self.base_url}/document/{document_id}/download",
                headers=self._auth_headers(),
                params={"type": "collapsed"},
            )
            resp.raise_for_status()
            return resp.content

    def add_fields(self, document_id: str, fields: list[dict]) -> dict:
        """
        Add signature/text fields to a document.

        Each field dict: {x, y, width, height, page_number, type, role, required}
        """
        with httpx.Client(timeout=30.0) as http:
            resp = http.put(
                f"{self.base_url}/document/{document_id}",
                headers={
                    **self._auth_headers(),
                    "Content-Type": "application/json",
                },
                json={"fields": fields},
            )
            resp.raise_for_status()
            return resp.json()

    # --- Invite operations ---

    def send_invite(
        self,
        document_id: str,
        signer_email: str,
        from_email: str,
        subject: str = "",
        message: str = "",
    ) -> dict:
        """Send a freeform signing invite to a single signer."""
        payload: dict = {"to": signer_email, "from": from_email}
        if subject:
            payload["subject"] = subject
        if message:
            payload["message"] = message

        with httpx.Client(timeout=30.0) as http:
            resp = http.post(
                f"{self.base_url}/document/{document_id}/invite",
                headers={
                    **self._auth_headers(),
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            resp.raise_for_status()
            return resp.json()

    def send_role_based_invite(
        self,
        document_id: str,
        signers: list[dict],
        from_email: str,
        subject: str = "",
        message: str = "",
    ) -> dict:
        """
        Send a role-based invite with field assignments.

        Each signer: {"email": ..., "role": ..., "role_id": ..., "order": ...}
        """
        payload: dict = {"to": signers, "from": from_email}
        if subject:
            payload["subject"] = subject
        if message:
            payload["message"] = message

        with httpx.Client(timeout=30.0) as http:
            resp = http.post(
                f"{self.base_url}/document/{document_id}/invite",
                headers={
                    **self._auth_headers(),
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            resp.raise_for_status()
            return resp.json()

    def cancel_invite(self, document_id: str) -> dict:
        """Cancel all pending invites for a document."""
        with httpx.Client(timeout=30.0) as http:
            resp = http.put(
                f"{self.base_url}/document/{document_id}/fieldinvitecancel",
                headers=self._auth_headers(),
            )
            resp.raise_for_status()
            return resp.json()

    # --- Template operations ---

    def list_templates(self) -> list[dict]:
        """List all templates in the account."""
        with httpx.Client(timeout=30.0) as http:
            resp = http.get(
                f"{self.base_url}/user/documentsv2",
                headers=self._auth_headers(),
                params={"template": "true"},
            )
            resp.raise_for_status()
            return resp.json()

    def create_document_from_template(self, template_id: str, name: str = "") -> dict:
        """Create a new document from a template. Returns {"id": ...}."""
        payload: dict = {}
        if name:
            payload["document_name"] = name

        with httpx.Client(timeout=30.0) as http:
            resp = http.post(
                f"{self.base_url}/template/{template_id}/copy",
                headers={
                    **self._auth_headers(),
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            resp.raise_for_status()
            return resp.json()

    # --- Webhook operations ---

    def register_webhook(
        self, event: str, entity_id: str, callback_url: str, secret: str = ""
    ) -> dict:
        """
        Register a webhook for a document event.

        event: e.g. "document.complete", "document.update"
        """
        payload: dict = {
            "event": event,
            "entity_id": entity_id,
            "action": "callback",
            "attributes": {
                "callback": callback_url,
                "use_tls_12": True,
            },
        }
        if secret:
            payload["attributes"]["secret_key"] = secret

        with httpx.Client(timeout=30.0) as http:
            resp = http.post(
                f"{self.base_url}/v2/events",
                headers={
                    **self._auth_headers(),
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            resp.raise_for_status()
            return resp.json()
