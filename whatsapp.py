"""
whatsapp.py
===========
Low-level helpers for interacting with the Meta WhatsApp Business (Graph) API.

Responsibilities:
  1. ``get_media_url``   – Resolve a Media ID to its temporary download URL.
  2. ``download_media``  – Download image binary from the resolved URL into memory.
  3. ``send_text_message`` – Post an outbound text reply back to a WhatsApp user.

All functions raise ``requests.HTTPError`` on non-2xx responses so callers can
handle failures in a centralised way.

Environment variables consumed (loaded by main.py via python-dotenv):
  WHATSAPP_ACCESS_TOKEN   – Bearer token for Graph API authentication.
  WHATSAPP_PHONE_NUMBER_ID – Sender phone number ID for outbound messages.
"""

import io
import logging
import os

import requests

# ── Module-level logger ───────────────────────────────────────────────────────
logger = logging.getLogger(__name__)

# Graph API base URL – pinned to v18.0 as specified in the requirements.
GRAPH_API_BASE = "https://graph.facebook.com/v18.0"


def _auth_headers() -> dict:
    """Return the Authorization header dict required by every Graph API call."""
    token = os.environ["WHATSAPP_ACCESS_TOKEN"]
    return {"Authorization": f"Bearer {token}"}


# ── Media helpers ─────────────────────────────────────────────────────────────


def get_media_url(media_id: str) -> str:
    """
    Phase 3 – Step A: Resolve a WhatsApp Media ID to its temporary HTTPS URL.

    Meta's Graph API returns a short-lived URL that must be fetched within a
    few minutes.  Always call this immediately before ``download_media``.

    Args:
        media_id: The opaque media identifier extracted from the webhook payload
                  (``messages[0].image.id``).

    Returns:
        The temporary HTTPS URL pointing to the raw image binary.

    Raises:
        requests.HTTPError: If the Graph API returns a non-2xx status code.
        KeyError: If the response JSON does not contain a ``url`` field.
    """
    url = f"{GRAPH_API_BASE}/{media_id}"
    logger.debug("Resolving media URL for media_id=%s", media_id)

    response = requests.get(url, headers=_auth_headers(), timeout=10)
    response.raise_for_status()

    media_url: str = response.json()["url"]
    logger.debug("Resolved media_id=%s → %s", media_id, media_url)
    return media_url


def download_media(media_url: str) -> bytes:
    """
    Phase 3 – Step B: Download the raw image binary from the resolved URL.

    The image is streamed into an in-memory ``io.BytesIO`` buffer and returned
    as plain ``bytes``.  No file is written to disk, satisfying the requirement
    that files must not be stored permanently.

    Args:
        media_url: The temporary URL returned by ``get_media_url``.

    Returns:
        Raw image bytes ready to be forwarded to the Gemini API.

    Raises:
        requests.HTTPError: If the CDN/Graph API returns a non-2xx status code.
    """
    logger.debug("Downloading media from URL")
    response = requests.get(media_url, headers=_auth_headers(), timeout=30)
    response.raise_for_status()

    buffer = io.BytesIO(response.content)
    image_bytes = buffer.read()
    logger.debug("Downloaded %d bytes", len(image_bytes))
    return image_bytes


# ── Outbound messaging ────────────────────────────────────────────────────────


def send_text_message(to: str, body: str) -> dict:
    """
    Phase 5: Send a plain-text WhatsApp message to a recipient.

    Constructs the standard Meta messages payload and POSTs it to the Graph API
    messages endpoint using the configured Phone Number ID as the sender.

    Args:
        to:   Recipient's full international phone number (e.g. ``"15551234567"``).
              Do not include a leading ``+``; Meta expects the raw E.164 digits.
        body: The text content to deliver (Gemini's generated response).

    Returns:
        The parsed JSON response dict from the Graph API (contains ``messages``
        with the WhatsApp message ID on success).

    Raises:
        requests.HTTPError: If the Graph API returns a non-2xx status code.
        KeyError: If ``WHATSAPP_PHONE_NUMBER_ID`` is not set in the environment.
    """
    phone_number_id = os.environ["WHATSAPP_PHONE_NUMBER_ID"]
    endpoint = f"{GRAPH_API_BASE}/{phone_number_id}/messages"

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": body},
    }

    headers = {
        **_auth_headers(),
        "Content-Type": "application/json",
    }

    logger.info("Sending WhatsApp message to %s", to)
    response = requests.post(endpoint, json=payload, headers=headers, timeout=10)
    response.raise_for_status()

    result: dict = response.json()
    logger.debug("Graph API response: %s", result)
    return result
