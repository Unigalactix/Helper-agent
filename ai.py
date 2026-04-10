"""
ai.py
=====
Google Gemini multimodal integration for the WhatsApp-Gemini webhook service.

Responsibilities:
  1. Instantiate a ``google.genai.Client`` once at module import time.
  2. Expose ``analyse_images`` – the single public entry point that accepts one
     or more raw image byte-strings, builds a multimodal prompt, and returns the
     model's text response.

Environment variables consumed (loaded by main.py via python-dotenv):
  GEMINI_API_KEY – API key obtained from Google AI Studio.

Notes
-----
* The module uses ``gemini-1.5-pro`` as specified in the requirements.  This
  model supports up to 16 images per request, which is well above the practical
  multi-image batching window used by this service.
* SDK: ``google-genai`` is the current, officially supported Google Gen AI SDK
  (``google-generativeai`` reached end-of-life November 30, 2025).
* Content safety: if Gemini blocks a response due to safety filters,
  ``response.text`` raises ``ValueError``.  This module catches that and
  returns a user-friendly fallback message instead of crashing.
* Timeout: a ``google.genai.errors.DeadlineExceeded`` (or the underlying
  ``google.api_core`` variant) is caught and surfaced as an error string.
"""

import logging
import os

from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types

# ── Module-level logger ───────────────────────────────────────────────────────
logger = logging.getLogger(__name__)

# ── One-time client instantiation ────────────────────────────────────────────
# ``genai.Client`` is constructed once at module import time and reused for
# every request, avoiding the overhead of re-authenticating on each call.
_client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

# ── Model selection ───────────────────────────────────────────────────────────
# gemini-1.5-pro supports text + image (multimodal) input natively.
_MODEL_NAME = "gemini-1.5-pro"

# ── System prompt ─────────────────────────────────────────────────────────────
# Customise this string to change how Gemini interprets every image it receives.
# Keep it concise – the model prepends it to each generation request.
SYSTEM_PROMPT = (
    "You are a helpful visual assistant. "
    "Carefully analyse the provided image(s) and give a clear, detailed, "
    "and accurate description or answer based solely on what you observe. "
    "If the image contains text, transcribe it faithfully. "
    "If it contains a product, scene, or document, describe the key details. "
    "Always respond in the same language the user appears to be using."
)


# ── Public API ────────────────────────────────────────────────────────────────


def analyse_images(image_bytes_list: list[bytes], mime_type: str = "image/jpeg") -> str:
    """
    Phase 4: Send one or more images to Gemini and return the generated text.

    This function is the only public interface in this module.  It accepts a
    list of raw image byte-strings (supporting Phase 6's multi-image batching)
    and submits them together with ``SYSTEM_PROMPT`` in a single API call.

    Args:
        image_bytes_list: Non-empty list of raw image data.  Each element is the
                          ``bytes`` returned by ``whatsapp.download_media``.
        mime_type:        MIME type shared by all images in the batch.  Defaults
                          to ``"image/jpeg"`` which covers the vast majority of
                          WhatsApp image uploads.  Change to ``"image/png"`` etc.
                          if needed.

    Returns:
        The model's text response as a plain Python string.  Returns a
        user-friendly error message string (rather than raising) when the model
        cannot produce a safe response or the API times out, so the caller can
        always forward *something* back to the WhatsApp user.

    Raises:
        ValueError: If ``image_bytes_list`` is empty (programming error, not an
                    API error – callers should guard against empty lists).
    """
    if not image_bytes_list:
        raise ValueError("image_bytes_list must contain at least one image.")

    logger.info(
        "Sending %d image(s) to Gemini model=%s", len(image_bytes_list), _MODEL_NAME
    )

    # Build the contents list accepted by the new SDK:
    #   [ system_prompt_part, inline_image_part_1, inline_image_part_2, … ]
    # The leading text part acts as a system-level instruction prepended to
    # every generation request.
    contents: list[genai_types.Part] = [genai_types.Part.from_text(text=SYSTEM_PROMPT)]
    for idx, img_bytes in enumerate(image_bytes_list):
        contents.append(
            genai_types.Part.from_bytes(data=img_bytes, mime_type=mime_type)
        )
        logger.debug(
            "Added image %d/%d (%d bytes)", idx + 1, len(image_bytes_list), len(img_bytes)
        )

    try:
        response = _client.models.generate_content(
            model=_MODEL_NAME,
            contents=contents,
        )
        # ``response.text`` raises ValueError if the response was blocked by
        # safety filters (finish_reason is SAFETY or prompt_feedback is set).
        result: str = response.text
        logger.info("Gemini returned %d characters", len(result))
        return result

    except ValueError as exc:
        # Safety filter triggered – do not expose internal details to the user.
        logger.warning("Gemini safety filter blocked the response: %s", exc)
        return (
            "I'm sorry, I wasn't able to process that image due to content "
            "safety restrictions. Please try a different image."
        )

    except genai_errors.DeadlineExceeded as exc:
        logger.error("Gemini API request timed out: %s", exc)
        return (
            "I'm sorry, the image analysis timed out. "
            "Please try again in a moment."
        )

    except genai_errors.APIError as exc:
        logger.error("Gemini API error: %s", exc)
        return (
            "I'm sorry, an error occurred while analysing your image. "
            "Please try again later."
        )
