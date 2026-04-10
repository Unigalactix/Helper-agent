"""
main.py
=======
WhatsApp ↔ Gemini Webhook Microservice
======================================

Entry point for the FastAPI application.  This module wires together all phases
of the pipeline described in the architecture specification:

  Phase 1 – Webhook verification  (GET /webhook)
  Phase 2 – Payload ingestion     (POST /webhook)
  Phase 3 – Media download        (via whatsapp.py)
  Phase 4 – Gemini analysis       (via ai.py)
  Phase 5 – WhatsApp reply        (via whatsapp.py)
  Phase 6 – Multi-image debounce  (in-memory cache with per-user timers)

Running locally
---------------
  1. Copy `.env.example` to `.env` and fill in the real values.
  2. Install dependencies:  ``pip install -r requirements.txt``
  3. Start the server:       ``uvicorn main:app --reload --port 8000``

The service is designed for deployment on a serverless platform (Cloud Run,
Azure Container Apps, etc.).  ``uvicorn`` is used as the ASGI server.

Architecture overview
---------------------
                 ┌──────────────────────────────────┐
  Meta           │  FastAPI (main.py)                │
  Webhook ──────►│  GET  /webhook  (verification)   │
  events         │  POST /webhook  (image ingestion) │
                 └──────────┬───────────────────────┘
                            │ BackgroundTask
                 ┌──────────▼───────────────────────┐
                 │  Debounce Cache                   │
                 │  { phone → [media_id, …], timer } │
                 └──────────┬───────────────────────┘
                            │ on TTL expiry
          ┌─────────────────▼──────────────────────────────────┐
          │  process_images_for_user()                          │
          │   1. download each media ID  (whatsapp.py)          │
          │   2. send all bytes to Gemini (ai.py)               │
          │   3. reply to user           (whatsapp.py)          │
          └─────────────────────────────────────────────────────┘
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse

# Load .env before importing ai.py (which instantiates the genai.Client at import time)
load_dotenv()

from ai import analyse_images  # noqa: E402  (must come after load_dotenv)
from whatsapp import download_media, get_media_url, send_text_message  # noqa: E402

# ── Logging configuration ─────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s – %(message)s",
)
logger = logging.getLogger(__name__)

# ── Multi-image debounce cache ────────────────────────────────────────────────
# Structure:
#   _image_cache[phone_number] = {
#       "media_ids": ["id1", "id2", …],   # accumulated media IDs
#       "task":      asyncio.TimerHandle,  # pending debounce timer
#   }
#
# When a new image arrives for a user:
#   • If no entry exists → create one and schedule a 5-second timer.
#   • If an entry exists → append the media ID and *reset* the timer.
# When the timer fires → trigger process_images_for_user and delete the entry.

_image_cache: dict[str, dict] = {}

# Debounce window in seconds (Phase 6).  Adjust as needed.
DEBOUNCE_TTL = 5.0


# ── Application lifespan ──────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Startup / shutdown lifecycle hook.

    On startup:  Logs the loaded configuration (without exposing secrets) and
                 verifies that the mandatory environment variables are present.
    On shutdown: Cancels any pending debounce timers to avoid fire-and-forget
                 tasks outliving the process.
    """
    # ── Startup ───────────────────────────────────────────────────────────────
    required_vars = [
        "WHATSAPP_ACCESS_TOKEN",
        "WHATSAPP_VERIFY_TOKEN",
        "WHATSAPP_PHONE_NUMBER_ID",
        "GEMINI_API_KEY",
    ]
    missing = [v for v in required_vars if not os.environ.get(v)]
    if missing:
        raise RuntimeError(
            f"Missing required environment variables: {', '.join(missing)}"
        )
    logger.info("WhatsApp-Gemini webhook service starting up ✓")

    yield  # ── Application runs here ─────────────────────────────────────────

    # ── Shutdown ──────────────────────────────────────────────────────────────
    logger.info("Cancelling %d pending debounce timers …", len(_image_cache))
    for entry in _image_cache.values():
        handle: asyncio.TimerHandle | None = entry.get("task")
        if handle:
            handle.cancel()
    _image_cache.clear()
    logger.info("WhatsApp-Gemini webhook service shut down ✓")


# ── FastAPI application ───────────────────────────────────────────────────────

app = FastAPI(
    title="WhatsApp-Gemini Webhook",
    description=(
        "Microservice that receives WhatsApp image messages, analyses them "
        "with Google Gemini, and replies with the generated text."
    ),
    version="1.0.0",
    lifespan=lifespan,
)


# ── Phase 1: Webhook Verification ────────────────────────────────────────────


@app.get(
    "/webhook",
    summary="Meta webhook verification",
    description=(
        "Meta calls this endpoint once when you register (or update) a "
        "webhook subscription.  The service validates the ``hub.verify_token`` "
        "query parameter and echoes back the ``hub.challenge`` value."
    ),
    response_class=PlainTextResponse,
)
async def verify_webhook(request: Request) -> PlainTextResponse:
    """
    Phase 1 – Webhook verification.

    Meta sends a GET request with three query parameters:
      - ``hub.mode``         must equal ``"subscribe"``
      - ``hub.verify_token`` must match ``WHATSAPP_VERIFY_TOKEN`` from the env
      - ``hub.challenge``    arbitrary string; echo it back to confirm ownership

    Returns:
        The ``hub.challenge`` value as plain text with HTTP 200 on success.

    Raises:
        HTTPException 403: If ``hub.mode`` is not ``"subscribe"`` or the
                           verify token does not match.
    """
    params = request.query_params
    mode = params.get("hub.mode")
    verify_token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    expected_token = os.environ["WHATSAPP_VERIFY_TOKEN"]

    if mode == "subscribe" and verify_token == expected_token:
        logger.info("Webhook verification successful")
        return PlainTextResponse(content=challenge, status_code=200)

    logger.warning(
        "Webhook verification failed – mode=%s, token_match=%s",
        mode,
        verify_token == expected_token,
    )
    raise HTTPException(status_code=403, detail="Verification failed")


# ── Phase 2: Payload Ingestion ────────────────────────────────────────────────


@app.post(
    "/webhook",
    summary="Receive incoming WhatsApp messages",
    description=(
        "Meta delivers all incoming messages and status updates to this endpoint. "
        "The service parses the payload, acknowledges immediately with HTTP 200 "
        "(to prevent Meta retrying delivery), and schedules asynchronous image "
        "processing via ``BackgroundTasks``."
    ),
    status_code=200,
)
async def receive_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    Phase 2 – Ingestion and quick acknowledgement.

    Parses the standard Meta WhatsApp Cloud API webhook payload.  Only ``image``
    type messages trigger further processing; all other events (text, status
    updates, etc.) are silently acknowledged.

    The heavy work (Phase 3–5) is pushed to a background task so this handler
    returns 200 in well under Meta's 20-second timeout.
    """
    try:
        body = await request.json()
    except Exception:
        # Invalid JSON – still return 200 to prevent Meta from retrying.
        logger.warning("Received non-JSON webhook payload; ignoring.")
        return {"status": "ok"}

    # Guard against notification payloads that don't carry messages
    # (e.g. message-status updates, account-review events, etc.)
    try:
        messages = body["entry"][0]["changes"][0]["value"].get("messages")
    except (KeyError, IndexError, TypeError):
        logger.debug("Webhook payload contains no actionable messages; ignoring.")
        return {"status": "ok"}

    if not messages:
        return {"status": "ok"}

    message = messages[0]
    sender: str = message["from"]
    msg_type: str = message.get("type", "")

    logger.info("Received message type=%s from=%s", msg_type, sender)

    if msg_type == "image":
        media_id: str = message["image"]["id"]
        logger.info("Queuing image media_id=%s for sender=%s", media_id, sender)
        # Schedule the debounce logic as a background task.
        background_tasks.add_task(_enqueue_image, sender, media_id)

    return {"status": "ok"}


# ── Phase 6: Multi-image debounce logic ───────────────────────────────────────


async def _enqueue_image(sender: str, media_id: str) -> None:
    """
    Phase 6 – Debounce incoming images from the same sender.

    Called in the background for every image message.  Accumulates media IDs
    for ``DEBOUNCE_TTL`` seconds; once the window closes without new images, it
    forwards all collected IDs to ``process_images_for_user``.

    Args:
        sender:   Sender's phone number (cache key).
        media_id: WhatsApp media ID of the newly arrived image.
    """
    loop = asyncio.get_event_loop()

    if sender in _image_cache:
        # Cancel the existing timer and append the new media ID.
        existing_task: asyncio.TimerHandle | None = _image_cache[sender].get("task")
        if existing_task:
            existing_task.cancel()
        _image_cache[sender]["media_ids"].append(media_id)
        logger.debug(
            "Debounce: appended media_id=%s for sender=%s (%d images queued)",
            media_id, sender, len(_image_cache[sender]["media_ids"]),
        )
    else:
        # First image for this sender in this window.
        _image_cache[sender] = {"media_ids": [media_id], "task": None}
        logger.debug(
            "Debounce: new entry for sender=%s, media_id=%s", sender, media_id
        )

    # (Re)schedule the flush timer.
    handle = loop.call_later(
        DEBOUNCE_TTL,
        lambda: asyncio.ensure_future(_flush_images(sender)),
    )
    _image_cache[sender]["task"] = handle


async def _flush_images(sender: str) -> None:
    """
    Triggered when the debounce TTL expires for a sender.

    Pops the accumulated media IDs from the cache and invokes
    ``process_images_for_user`` with the complete batch.
    """
    entry = _image_cache.pop(sender, None)
    if not entry:
        return

    media_ids: list[str] = entry["media_ids"]
    logger.info(
        "Debounce timer fired for sender=%s – processing %d image(s)",
        sender, len(media_ids),
    )
    await process_images_for_user(sender, media_ids)


# ── Phase 3–5: Core processing pipeline ──────────────────────────────────────


async def process_images_for_user(sender: str, media_ids: list[str]) -> None:
    """
    End-to-end image processing pipeline (Phases 3–5).

    For each media ID:
      1. Resolve the temporary download URL (Phase 3 – Step A).
      2. Download the image binary into memory (Phase 3 – Step B).

    Then:
      3. Send all downloaded images to Gemini in a single multimodal request
         (Phase 4).
      4. Post the resulting text back to the sender via WhatsApp (Phase 5).

    Errors at any step are caught and logged; a fallback error message is sent
    to the user so they always receive *some* reply.

    Args:
        sender:    Recipient's phone number for the outbound reply.
        media_ids: List of one or more WhatsApp media IDs to process.
    """
    logger.info(
        "Processing %d image(s) for sender=%s", len(media_ids), sender
    )

    # ── Phase 3: Download all images ─────────────────────────────────────────
    image_bytes_list: list[bytes] = []
    for media_id in media_ids:
        try:
            media_url = get_media_url(media_id)
            image_bytes = download_media(media_url)
            image_bytes_list.append(image_bytes)
            logger.debug("Downloaded media_id=%s (%d bytes)", media_id, len(image_bytes))
        except Exception as exc:
            logger.error("Failed to download media_id=%s: %s", media_id, exc)
            # Skip this image but continue with others in the batch.

    if not image_bytes_list:
        logger.error("All image downloads failed for sender=%s; sending error reply", sender)
        _safe_send(sender, "Sorry, I was unable to retrieve your image(s). Please try again.")
        return

    # ── Phase 4: Analyse with Gemini ─────────────────────────────────────────
    try:
        gemini_response = analyse_images(image_bytes_list)
    except Exception as exc:
        logger.error("Gemini analysis raised an unexpected exception: %s", exc)
        gemini_response = (
            "Sorry, something went wrong while analysing your image(s). "
            "Please try again later."
        )

    # ── Phase 5: Reply via WhatsApp ───────────────────────────────────────────
    _safe_send(sender, gemini_response)


def _safe_send(to: str, body: str) -> None:
    """
    Send a WhatsApp message, absorbing any exception to avoid crashing the
    background task and losing the conversation context.
    """
    try:
        send_text_message(to, body)
        logger.info("Reply sent successfully to %s", to)
    except Exception as exc:
        logger.error("Failed to send WhatsApp message to %s: %s", to, exc)
