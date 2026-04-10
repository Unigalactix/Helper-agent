# Helper-agent — WhatsApp ↔ Gemini Webhook Microservice

A lightweight FastAPI microservice that connects the **Meta WhatsApp Business Cloud API** to **Google Gemini**. When a user sends one or more images on WhatsApp, the bot analyses them with Gemini's multimodal vision model and replies with a detailed description — all in a matter of seconds.

---

## Table of Contents

1. [Features](#features)
2. [Architecture](#architecture)
3. [Project Structure](#project-structure)
4. [Prerequisites](#prerequisites)
5. [Quick Start](#quick-start)
6. [Environment Variables](#environment-variables)
7. [Running Locally](#running-locally)
8. [API Endpoints](#api-endpoints)
9. [How It Works — Pipeline Phases](#how-it-works--pipeline-phases)
10. [Multi-Image Debounce](#multi-image-debounce)
11. [Gemini Integration](#gemini-integration)
12. [Deployment](#deployment)
13. [Troubleshooting](#troubleshooting)
14. [Contributing](#contributing)

---

## Features

- **WhatsApp image analysis** — receive images from any WhatsApp user and reply with Gemini-generated descriptions.
- **Multi-image batching** — if a user sends several images in quick succession, the service debounces them into a single Gemini request (default 5-second window).
- **Multimodal Gemini** — uses `gemini-1.5-pro` via the latest `google-genai` SDK, supporting up to 16 images per request.
- **Webhook verification** — handles Meta's `GET /webhook` challenge/response flow automatically.
- **Non-blocking** — heavy image-processing work runs in a `BackgroundTask`; the webhook handler returns `200 OK` to Meta in milliseconds, well within the 20-second timeout.
- **Graceful error handling** — safety-filter blocks, API timeouts, and download failures all produce a friendly fallback message to the user instead of crashing.
- **Zero disk I/O** — images are held in memory only and never written to disk.
- **Cloud-ready** — stateless design suitable for Cloud Run, Render, Koyeb, Fly.io, Railway, or any ASGI host.

---

## Architecture

```
Meta Webhook Events
        │
        ▼
┌───────────────────────────────────┐
│  FastAPI (main.py)                │
│  GET  /webhook  ← verification   │
│  POST /webhook  ← image messages │
└───────────────┬───────────────────┘
                │ BackgroundTask
                ▼
┌───────────────────────────────────┐
│  Debounce Cache (in-memory)       │
│  { phone → [media_id, …], timer } │
└───────────────┬───────────────────┘
                │ fires after 5 s of silence
                ▼
┌────────────────────────────────────────────────┐
│  process_images_for_user()                      │
│  1. get_media_url()    → temporary HTTPS URL    │
│  2. download_media()   → raw image bytes        │
│  3. analyse_images()   → Gemini text response   │
│  4. send_text_message()→ WhatsApp reply         │
└────────────────────────────────────────────────┘
```

---

## Project Structure

```
Helper-agent/
├── main.py          # FastAPI app, webhook handlers, debounce logic
├── ai.py            # Google Gemini client and analyse_images()
├── whatsapp.py      # Meta Graph API helpers (download + send)
├── requirements.txt # Python dependencies
├── .env.example     # Template for environment variables
└── SETUP.md         # Full step-by-step setup guide (Meta + Gemini + hosting)
```

---

## Prerequisites

| Tool | Version | Purpose |
|---|---|---|
| Python | 3.11 + | Runtime |
| pip | any | Dependency manager |
| A Meta Developer account | — | WhatsApp Business API |
| A Google account | — | Gemini API key |

---

## Quick Start

```bash
# 1. Clone the repository
git clone https://github.com/Unigalactix/Helper-agent.git
cd Helper-agent

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment variables
cp .env.example .env
# Open .env and fill in the four values (see below)

# 4. Start the server
uvicorn main:app --reload --port 8000
```

For a **full walkthrough** — including how to create the Meta App, obtain API credentials, and deploy to a free cloud host — see **[SETUP.md](SETUP.md)**.

---

## Environment Variables

Copy `.env.example` to `.env` and fill in these four values before starting the service:

| Variable | Description |
|---|---|
| `WHATSAPP_ACCESS_TOKEN` | Bearer token from the Meta Developer Console (WhatsApp → API Setup). Can be a 24-hour temporary token for testing or a permanent System User token for production. |
| `WHATSAPP_VERIFY_TOKEN` | Any secret string you invent. Paste the same value into the Meta App webhook settings so Meta can confirm you own the endpoint. |
| `WHATSAPP_PHONE_NUMBER_ID` | The numeric Phone Number ID from Meta App → WhatsApp → API Setup. Used as the sender ID for outbound messages. |
| `GEMINI_API_KEY` | API key from [Google AI Studio](https://aistudio.google.com/). The free quota is generous for development use. |

> **Security:** Never commit your `.env` file to version control. The `.env.example` file is safe to commit — it contains only placeholder values.

---

## Running Locally

Meta's webhook requires a **public HTTPS URL**, so you need a tunnel during local development.

### Start the server

```bash
uvicorn main:app --reload --port 8000
```

### Expose port 8000 with ngrok

```bash
# Install once
brew install ngrok          # macOS
# or: pip install pyngrok   # cross-platform

# Authenticate (free account at https://ngrok.com/)
ngrok config add-authtoken YOUR_NGROK_TOKEN

# Expose port 8000
ngrok http 8000
```

ngrok will print a forwarding URL such as `https://abc123.ngrok-free.app`. Use:

```
https://abc123.ngrok-free.app/webhook
```

as the **Callback URL** when registering the webhook in the Meta Dashboard.

> **Tip:** The free ngrok URL changes every restart. For a stable free alternative, try [localtunnel](https://github.com/localtunnel/localtunnel): `npx localtunnel --port 8000`

---

## API Endpoints

### `GET /webhook` — Webhook verification

Meta calls this endpoint once when you register (or update) a webhook subscription.

| Query param | Description |
|---|---|
| `hub.mode` | Must be `"subscribe"` |
| `hub.verify_token` | Must match `WHATSAPP_VERIFY_TOKEN` |
| `hub.challenge` | Arbitrary string; echoed back to confirm ownership |

**Success → 200 OK** with the challenge string as the response body.  
**Failure → 403 Forbidden** if the token doesn't match.

---

### `POST /webhook` — Receive incoming messages

Meta delivers all incoming messages and status updates here.

- The handler **always returns `200 OK` immediately** to prevent Meta from retrying delivery.
- Only `image` type messages trigger further processing; all other message types and status updates are silently acknowledged.
- Image processing (download → Gemini → reply) runs asynchronously via `BackgroundTasks`.

---

## How It Works — Pipeline Phases

| Phase | Module | Description |
|---|---|---|
| **1 — Verification** | `main.py` | Responds to Meta's `GET /webhook` challenge |
| **2 — Ingestion** | `main.py` | Parses the `POST /webhook` payload; extracts `sender` and `media_id`; returns 200 immediately |
| **3 — Media download** | `whatsapp.py` | Resolves the media ID to a temporary URL (`get_media_url`), then downloads the raw bytes into memory (`download_media`) |
| **4 — Gemini analysis** | `ai.py` | Sends all buffered image bytes to `gemini-1.5-pro` via the `google-genai` SDK and returns the generated text |
| **5 — WhatsApp reply** | `whatsapp.py` | Posts the Gemini response back to the sender as a plain-text WhatsApp message (`send_text_message`) |
| **6 — Debounce** | `main.py` | Accumulates images sent in quick succession from the same user and forwards them as a single batch after a 5-second quiet window |

---

## Multi-Image Debounce

When users send several images at once on WhatsApp, they arrive as separate webhook events. The debounce mechanism groups them:

1. The **first** image from a sender starts a 5-second countdown timer and creates a cache entry.
2. Each **subsequent** image from the same sender within the window resets the timer and appends to the queue.
3. When the timer **expires** (5 seconds after the last image), all queued media IDs are flushed to `process_images_for_user` as a single batch.

The debounce window is configurable via the `DEBOUNCE_TTL` constant in `main.py` (default: `5.0` seconds).

The cache is in-memory and per-process. Pending timers are cancelled cleanly on server shutdown.

---

## Gemini Integration

File: `ai.py`

### Model

`gemini-1.5-pro` — Google's multimodal model supporting text + image input. Supports up to **16 images per request**.

### SDK

Uses the current `google-genai` package (not the deprecated `google-generativeai`, which reached end-of-life November 30, 2025).

### System prompt

Each request prepends a system-level instruction:

> *"You are a helpful visual assistant. Carefully analyse the provided image(s) and give a clear, detailed, and accurate description or answer based solely on what you observe. If the image contains text, transcribe it faithfully. If it contains a product, scene, or document, describe the key details. Always respond in the same language the user appears to be using."*

You can customise this by editing the `SYSTEM_PROMPT` constant in `ai.py`.

### Error handling

| Error type | Behaviour |
|---|---|
| Safety filter block (`ValueError`) | Returns a polite "content safety" message |
| API timeout (`DeadlineExceeded`) | Returns a "please try again" message |
| General API error (`APIError`) | Returns a generic error message |

---

## Deployment

The service is stateless and deploys easily to any platform that runs Python or Docker. See **[SETUP.md](SETUP.md)** for full deployment instructions for each option.

| Platform | Free tier | Cold starts | Notes |
|---|---|---|---|
| [Render](https://render.com) | 512 MB RAM | Yes (~30 s) | Spins down after 15 min inactivity on free tier |
| [Koyeb](https://www.koyeb.com) | 512 MB RAM, 0.1 vCPU | **No** | Always-on free tier; recommended |
| [Fly.io](https://fly.io) | 3 × 256 MB VMs | **No** | Credit card required to unlock full free allowance |
| [Railway](https://railway.app) | $5/month credit | **No** | ~500 hours/month on tiny instance |
| [Hugging Face Spaces](https://huggingface.co/spaces) | 2 vCPU, 16 GB RAM | Yes (~48 h) | Sleeps after 48 h inactivity; use UptimeRobot to keep alive |

### Start command (all platforms)

```bash
uvicorn main:app --host 0.0.0.0 --port $PORT
```

### Required environment variables (all platforms)

Set these in your platform's secrets / environment variables settings:

```
WHATSAPP_ACCESS_TOKEN
WHATSAPP_VERIFY_TOKEN
WHATSAPP_PHONE_NUMBER_ID
GEMINI_API_KEY
```

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Meta shows "Callback URL failed" on verification | Server not reachable or wrong `WHATSAPP_VERIFY_TOKEN` | Check server logs; ensure `WHATSAPP_VERIFY_TOKEN` in `.env` exactly matches the value entered in the Meta dashboard |
| No reply after sending an image | `WHATSAPP_ACCESS_TOKEN` expired | Regenerate the 24-hour token in Meta → WhatsApp → API Setup, or set up a permanent System User token |
| `RuntimeError: Missing required environment variables` on startup | One or more env vars not set | Verify all four variables are present in `.env` (local) or the platform's environment settings |
| `KeyError: 'GEMINI_API_KEY'` on startup | Env var not loaded | Ensure `.env` exists and is in the working directory, or set the variable directly in the shell |
| `requests.HTTPError: 401` | Invalid or expired access token | Regenerate `WHATSAPP_ACCESS_TOKEN` |
| Render cold-start causes Meta webhook timeout | Free tier spun down | Upgrade to paid Render, or switch to Koyeb / Fly.io for always-on free hosting |
| Images silently ignored | Message type is not `image` | The service only processes `image` messages; text, voice, and document messages are acknowledged but not processed |

---

## Contributing

1. Fork the repository and create a feature branch.
2. Make your changes, keeping commits focused and descriptive.
3. Open a pull request — please describe what you changed and why.

---

> **Full setup guide:** For step-by-step instructions on creating the Meta Developer App, obtaining credentials, running locally with a tunnel, and deploying to a free host, see **[SETUP.md](SETUP.md)**.
