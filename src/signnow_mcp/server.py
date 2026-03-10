"""MCP server exposing airSlate SignNow tools for Claude Code."""

import json
import os
import sys

import httpx
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from .client import SignNowClient

load_dotenv()

mcp = FastMCP(
    "signnow",
    instructions=(
        "Unofficial MCP server for airSlate SignNow e-signatures. "
        "Upload documents, send signing invites, check status, download signed PDFs, "
        "and manage templates. Requires SignNow API credentials (see .env.example)."
    ),
)

_client: SignNowClient | None = None


def _get_client() -> SignNowClient:
    global _client
    if _client is None:
        _client = SignNowClient()
    return _client


# --- Document tools ---


@mcp.tool()
def upload_document(file_path: str) -> str:
    """Upload a PDF file to SignNow for signing.

    Args:
        file_path: Absolute path to a PDF file on disk.

    Returns:
        JSON with the SignNow document ID.
    """
    path = os.path.expanduser(file_path)
    if not os.path.isfile(path):
        return json.dumps({"error": f"File not found: {path}"})

    filename = os.path.basename(path)
    with open(path, "rb") as f:
        pdf_bytes = f.read()

    try:
        result = _get_client().upload_document(pdf_bytes, filename)
        return json.dumps({"document_id": result.get("id", ""), "filename": filename})
    except httpx.HTTPStatusError as e:
        return json.dumps({"error": f"Upload failed: {e.response.status_code} {e.response.text}"})


@mcp.tool()
def get_document(document_id: str) -> str:
    """Get document details and signing status from SignNow.

    Args:
        document_id: The SignNow document ID.

    Returns:
        JSON with document name, status, roles, and field invite details.
    """
    try:
        doc = _get_client().get_document(document_id)
        return json.dumps({
            "id": doc.get("id"),
            "document_name": doc.get("document_name"),
            "page_count": doc.get("page_count"),
            "created": doc.get("created"),
            "updated": doc.get("updated"),
            "roles": doc.get("roles", []),
            "field_invites": doc.get("field_invites", []),
            "signatures": doc.get("signatures", []),
        })
    except httpx.HTTPStatusError as e:
        return json.dumps({"error": f"Failed: {e.response.status_code} {e.response.text}"})


@mcp.tool()
def list_documents() -> str:
    """List all documents in the SignNow account.

    Returns:
        JSON array of documents with id, name, and creation date.
    """
    try:
        docs = _get_client().list_documents()
        summary = [
            {
                "id": d.get("id"),
                "document_name": d.get("document_name"),
                "created": d.get("created"),
                "updated": d.get("updated"),
                "page_count": d.get("page_count"),
            }
            for d in docs
        ]
        return json.dumps(summary)
    except httpx.HTTPStatusError as e:
        return json.dumps({"error": f"Failed: {e.response.status_code} {e.response.text}"})


@mcp.tool()
def download_signed_document(document_id: str, save_path: str) -> str:
    """Download a signed PDF from SignNow and save it locally.

    Args:
        document_id: The SignNow document ID.
        save_path: Absolute path where the signed PDF should be saved.

    Returns:
        JSON confirming the download path and file size.
    """
    try:
        pdf_bytes = _get_client().download_document(document_id)
        path = os.path.expanduser(save_path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(pdf_bytes)
        return json.dumps({"saved_to": path, "size_bytes": len(pdf_bytes)})
    except httpx.HTTPStatusError as e:
        return json.dumps({"error": f"Download failed: {e.response.status_code} {e.response.text}"})


# --- Signing tools ---


@mcp.tool()
def send_signing_invite(
    document_id: str,
    signer_email: str,
    from_email: str,
    subject: str = "",
    message: str = "",
) -> str:
    """Send a freeform e-signature invite for a document.

    Args:
        document_id: The SignNow document ID.
        signer_email: Email address of the person who should sign.
        from_email: Sender email address (must be the SignNow account email).
        subject: Optional email subject line (paid plan feature).
        message: Optional email body message (paid plan feature).

    Returns:
        JSON with invite details.
    """
    try:
        result = _get_client().send_invite(
            document_id, signer_email, from_email, subject, message
        )
        return json.dumps(result)
    except httpx.HTTPStatusError as e:
        return json.dumps({"error": f"Invite failed: {e.response.status_code} {e.response.text}"})


@mcp.tool()
def send_role_based_invite(
    document_id: str,
    signers_json: str,
    from_email: str,
    subject: str = "",
    message: str = "",
) -> str:
    """Send a role-based signing invite with specific field assignments.

    Args:
        document_id: The SignNow document ID.
        signers_json: JSON array of signers, each with: email, role, role_id, order.
            Example: [{"email": "signer@example.com", "role": "Signer 1", "role_id": "abc123", "order": 1}]
        from_email: Sender email address.
        subject: Optional email subject line.
        message: Optional email body message.

    Returns:
        JSON with invite details.
    """
    try:
        signers = json.loads(signers_json)
    except json.JSONDecodeError as e:
        return json.dumps({"error": f"Invalid signers_json: {e}"})

    try:
        result = _get_client().send_role_based_invite(
            document_id, signers, from_email, subject, message
        )
        return json.dumps(result)
    except httpx.HTTPStatusError as e:
        return json.dumps({"error": f"Invite failed: {e.response.status_code} {e.response.text}"})


@mcp.tool()
def cancel_invite(document_id: str) -> str:
    """Cancel all pending signing invites for a document.

    Args:
        document_id: The SignNow document ID.

    Returns:
        JSON confirmation.
    """
    try:
        result = _get_client().cancel_invite(document_id)
        return json.dumps(result)
    except httpx.HTTPStatusError as e:
        return json.dumps({"error": f"Cancel failed: {e.response.status_code} {e.response.text}"})


# --- Field tools ---


@mcp.tool()
def add_signature_field(
    document_id: str,
    x: int = 350,
    y: int = 700,
    width: int = 200,
    height: int = 50,
    page_number: int = 0,
    role: str = "Signer 1",
) -> str:
    """Add a signature field to a document at the specified position.

    Args:
        document_id: The SignNow document ID.
        x: Horizontal position in pixels (default: 350).
        y: Vertical position in pixels (default: 700).
        width: Field width in pixels (default: 200).
        height: Field height in pixels (default: 50).
        page_number: Zero-based page index (default: 0).
        role: Signer role name (default: "Signer 1").

    Returns:
        JSON confirmation with document details.
    """
    fields = [
        {
            "x": x,
            "y": y,
            "width": width,
            "height": height,
            "page_number": page_number,
            "type": "signature",
            "role": role,
            "required": True,
        }
    ]
    try:
        result = _get_client().add_fields(document_id, fields)
        return json.dumps(result)
    except httpx.HTTPStatusError as e:
        return json.dumps({"error": f"Failed: {e.response.status_code} {e.response.text}"})


# --- Template tools ---


@mcp.tool()
def list_templates() -> str:
    """List all document templates in the SignNow account.

    Returns:
        JSON array of templates with id and name.
    """
    try:
        templates = _get_client().list_templates()
        summary = [
            {"id": t.get("id"), "document_name": t.get("document_name")}
            for t in templates
        ]
        return json.dumps(summary)
    except httpx.HTTPStatusError as e:
        return json.dumps({"error": f"Failed: {e.response.status_code} {e.response.text}"})


@mcp.tool()
def create_from_template(template_id: str, document_name: str = "") -> str:
    """Create a new document from a SignNow template.

    Args:
        template_id: The template ID to copy from.
        document_name: Optional name for the new document.

    Returns:
        JSON with the new document ID.
    """
    try:
        result = _get_client().create_document_from_template(template_id, document_name)
        return json.dumps(result)
    except httpx.HTTPStatusError as e:
        return json.dumps({"error": f"Failed: {e.response.status_code} {e.response.text}"})


# --- Webhook tools ---


@mcp.tool()
def register_webhook(
    document_id: str,
    callback_url: str,
    event: str = "document.complete",
) -> str:
    """Register a webhook to be notified when a document event occurs.

    Args:
        document_id: The SignNow document ID to watch.
        callback_url: Public URL that will receive the webhook POST.
        event: Event type (default: "document.complete"). Other: "document.update".

    Returns:
        JSON confirmation.
    """
    secret = os.getenv("SIGNNOW_WEBHOOK_SECRET", "")
    try:
        result = _get_client().register_webhook(event, document_id, callback_url, secret)
        return json.dumps(result)
    except httpx.HTTPStatusError as e:
        return json.dumps({"error": f"Failed: {e.response.status_code} {e.response.text}"})


def main():
    mcp.run()


if __name__ == "__main__":
    main()
