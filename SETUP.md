# Setup Guide

End-to-end instructions for running the WhatsApp ↔ Gemini webhook service —
from creating a Meta Developer App to deploying on a **free** hosting platform.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [WhatsApp Business API Setup](#2-whatsapp-business-api-setup)
3. [Gemini API Key](#3-gemini-api-key)
4. [Run Locally (with a public tunnel)](#4-run-locally-with-a-public-tunnel)
5. [Free Hosting Options](#5-free-hosting-options)
   - [Render](#render-recommended)
   - [Koyeb](#koyeb)
   - [Fly.io](#flyio)
   - [Railway](#railway)
   - [Hugging Face Spaces](#hugging-face-spaces)
6. [Register the Webhook URL in Meta](#6-register-the-webhook-url-in-meta)
7. [Verify Everything Works](#7-verify-everything-works)

---

## 1. Prerequisites

| Tool | Why |
|---|---|
| Python 3.11+ | Runtime for this service |
| pip | Install Python dependencies |
| git | Clone the repo |
| A Meta (Facebook) account | Required for the WhatsApp Business API |
| A Google account | Required for Gemini API key |

Clone and install:

```bash
git clone https://github.com/Unigalactix/Helper-agent.git
cd Helper-agent
pip install -r requirements.txt
cp .env.example .env   # then fill in your values (see sections below)
```

---

## 2. WhatsApp Business API Setup

Meta provides a **free test environment** — no business verification or paid
subscription is required to get started.

### Step 1 — Create a Meta Developer account

1. Go to <https://developers.facebook.com/> and log in with your Facebook account.
2. Click **My Apps → Create App**.
3. Choose **"Other"** as the use case, then **"Business"** as the app type.
4. Give the app a name (e.g. `Helper-agent`) and click **Create App**.

### Step 2 — Add the WhatsApp product

1. In your new app's dashboard, scroll down to **"Add Products to Your App"**.
2. Find **WhatsApp** and click **Set Up**.
3. You now have a **WhatsApp Business Platform** section in the left sidebar.

### Step 3 — Get your credentials

Navigate to **WhatsApp → API Setup** in the sidebar.

| Field | Where to find it | `.env` variable |
|---|---|---|
| **Temporary access token** | Shown at the top of the API Setup page (valid for 24 h; a permanent token requires a System User — see note below) | `WHATSAPP_ACCESS_TOKEN` |
| **Phone Number ID** | "From" dropdown on the same page — copy the **numeric ID** shown next to the test number | `WHATSAPP_PHONE_NUMBER_ID` |

> **Permanent token (optional):** Go to **Business Settings → System Users → Add**, create
> a System User, assign the app with `whatsapp_business_messaging` permission, then generate
> a token with no expiry. Paste that token as `WHATSAPP_ACCESS_TOKEN`.

### Step 4 — Add a recipient number (test environment only)

1. On the **API Setup** page, under **"To"**, click **Add phone number**.
2. Enter your personal WhatsApp number and complete the OTP verification.
3. You can now send test messages **to that number** using the test phone number provided by Meta.

### Step 5 — Choose your Verify Token

Open your `.env` file and set `WHATSAPP_VERIFY_TOKEN` to any secret string you
invent (e.g. `my-super-secret-token-123`).  You will paste this same value into
the Meta dashboard when registering the webhook in [Step 6](#6-register-the-webhook-url-in-meta).

---

## 3. Gemini API Key

1. Go to <https://aistudio.google.com/>.
2. Sign in with your Google account.
3. Click **Get API key → Create API key in new project** (free quota is generous).
4. Copy the key and paste it as `GEMINI_API_KEY` in your `.env`.

---

## 4. Run Locally (with a public tunnel)

Meta's webhook requires a **public HTTPS URL**.  Use a tunnel tool during
development so you don't need to deploy yet.

### Using ngrok (recommended)

```bash
# Install (one-time)
# macOS / Linux
brew install ngrok       # or: pip install pyngrok

# Windows
choco install ngrok      # or download from https://ngrok.com/download

# Sign up for a free account at https://ngrok.com/ and authenticate:
ngrok config add-authtoken YOUR_NGROK_TOKEN

# In terminal 1 – start the FastAPI server
uvicorn main:app --reload --port 8000

# In terminal 2 – expose port 8000 to the internet
ngrok http 8000
```

ngrok prints a line like:

```
Forwarding   https://abc123.ngrok-free.app -> http://localhost:8000
```

Use `https://abc123.ngrok-free.app/webhook` as your webhook URL in Meta.

> **Note:** The free ngrok URL changes every time you restart the tunnel.
> For a stable URL without signing up, try [localtunnel](https://github.com/localtunnel/localtunnel):
> `npx localtunnel --port 8000`

---

## 5. Free Hosting Options

All five options below support Python/FastAPI, provide HTTPS out of the box,
and have a free tier with no credit card required (except where noted).

---

### Render (recommended)

**Free tier:** 512 MB RAM, 0.1 CPU, unlimited bandwidth.  
**Caveat:** Free web services spin down after ~15 minutes of inactivity; the
first request after a cold-start takes ~30 seconds.  Upgrade to the $7/month
plan for always-on.

#### Deploy steps

1. Push your code to a GitHub repo (already done if you forked this one).
2. Go to <https://render.com/> and sign up with GitHub.
3. Click **New → Web Service** and connect your repo.
4. Configure:
   | Setting | Value |
   |---|---|
   | **Runtime** | Python 3 |
   | **Build Command** | `pip install -r requirements.txt` |
   | **Start Command** | `uvicorn main:app --host 0.0.0.0 --port $PORT` |
5. Under **Environment**, add the four variables from your `.env`:
   - `WHATSAPP_ACCESS_TOKEN`
   - `WHATSAPP_VERIFY_TOKEN`
   - `WHATSAPP_PHONE_NUMBER_ID`
   - `GEMINI_API_KEY`
6. Click **Create Web Service**. Render assigns a URL like
   `https://helper-agent.onrender.com`.
7. Use `https://helper-agent.onrender.com/webhook` in Meta.

---

### Koyeb

**Free tier:** 1 nano instance (512 MB RAM, 0.1 vCPU) — **always-on**, no cold starts.  
No credit card required.

#### Deploy steps

1. Go to <https://www.koyeb.com/> and sign up.
2. Click **Create Service → GitHub** and connect your repo.
3. Configure:
   | Setting | Value |
   |---|---|
   | **Builder** | Buildpack (auto-detected) |
   | **Run command** | `uvicorn main:app --host 0.0.0.0 --port 8000` |
   | **Port** | `8000` |
4. Add the four environment variables in the **Environment variables** section.
5. Deploy. Koyeb assigns a URL like `https://helper-agent-yourname.koyeb.app`.
6. Use `https://helper-agent-yourname.koyeb.app/webhook` in Meta.

---

### Fly.io

**Free tier:** 3 shared-CPU VMs with 256 MB RAM each (always-on).  
Requires a credit card to unlock the full free allowance (card is not charged).

#### Deploy steps

```bash
# Install the Fly CLI
curl -L https://fly.io/install.sh | sh    # Linux/macOS
# Windows: https://fly.io/docs/hands-on/install-flyctl/

# Log in
fly auth login

# Inside your repo directory
fly launch          # creates fly.toml; choose the free shared-cpu-1x size
```

When prompted:
- **App name:** e.g. `helper-agent`
- **Region:** pick the one nearest your users
- **Postgres / Redis:** No (not needed)

Set environment variables (do **not** put secrets in `fly.toml`):

```bash
fly secrets set WHATSAPP_ACCESS_TOKEN="..." \
                WHATSAPP_VERIFY_TOKEN="..." \
                WHATSAPP_PHONE_NUMBER_ID="..." \
                GEMINI_API_KEY="..."
```

Create a minimal `Dockerfile` in the repo root (Fly.io uses it automatically):

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
```

Deploy:

```bash
fly deploy
```

Your app URL: `https://helper-agent.fly.dev`  
Webhook URL: `https://helper-agent.fly.dev/webhook`

---

### Railway

**Free tier:** $5 USD of compute credit per month (enough for ~500 hours of a
tiny instance).  No credit card required for the Starter plan.

#### Deploy steps

1. Go to <https://railway.app/> and sign up with GitHub.
2. Click **New Project → Deploy from GitHub repo** and select your repo.
3. Railway auto-detects Python. Add a **Start Command** in the service settings:
   ```
   uvicorn main:app --host 0.0.0.0 --port $PORT
   ```
4. Under **Variables**, add the four environment variables.
5. Under **Settings → Networking**, click **Generate Domain** to get a public
   HTTPS URL (e.g. `https://helper-agent-production.up.railway.app`).
6. Use `https://helper-agent-production.up.railway.app/webhook` in Meta.

---

### Hugging Face Spaces

**Free tier:** 2 vCPU, 16 GB RAM (ZeroGPU Spaces) — permanently free.  
Best if you already have a Hugging Face account.

#### Deploy steps

1. Go to <https://huggingface.co/spaces> and click **Create new Space**.
2. Choose:
   | Setting | Value |
   |---|---|
   | **SDK** | Docker |
   | **Hardware** | CPU Basic (free) |
3. Commit a `Dockerfile` (same as the Fly.io one above) and your source files.
4. In the Space's **Settings → Repository secrets**, add the four environment variables.
5. Your space URL: `https://YOUR_USERNAME-helper-agent.hf.space`  
   Webhook URL: `https://YOUR_USERNAME-helper-agent.hf.space/webhook`

> **Note:** Hugging Face Spaces go to sleep after ~48 hours without activity on
> the free CPU tier.  Keep the space awake by pinging it regularly (e.g. via a
> free UptimeRobot monitor at <https://uptimerobot.com/>).

---

## 6. Register the Webhook URL in Meta

Once your server is running and publicly reachable:

1. Open your Meta App → **WhatsApp → Configuration** (left sidebar).
2. Under **Webhook**, click **Edit**.
3. Fill in:
   | Field | Value |
   |---|---|
   | **Callback URL** | `https://<your-host>/webhook` |
   | **Verify token** | the value you set for `WHATSAPP_VERIFY_TOKEN` |
4. Click **Verify and Save**.  
   Meta will send a `GET /webhook?hub.mode=subscribe&hub.verify_token=...&hub.challenge=...`
   request; your server responds with the challenge, and Meta shows **"Verified ✓"**.
5. Under **Webhook fields**, click **Manage**, find **messages**, and toggle it on.
6. Click **Done**.

---

## 7. Verify Everything Works

### Quick smoke test

Send an image from your verified WhatsApp number to the test number provided
by Meta.  Within a few seconds you should receive Gemini's analysis back as a
WhatsApp reply.

### Check logs

| Platform | How to view logs |
|---|---|
| **Local** | Terminal running `uvicorn` |
| **Render** | Dashboard → your service → **Logs** tab |
| **Koyeb** | Dashboard → your service → **Logs** tab |
| **Fly.io** | `fly logs` in the CLI |
| **Railway** | Dashboard → your service → **Deploy Logs** |
| **Hugging Face** | Space → **Logs** tab |

### Common issues

| Symptom | Likely cause | Fix |
|---|---|---|
| Meta shows "Callback URL failed" on verification | Server not reachable or wrong `WHATSAPP_VERIFY_TOKEN` | Check logs; ensure the server is running and the token matches exactly |
| No reply after sending image | `WHATSAPP_ACCESS_TOKEN` expired | Regenerate the token in Meta API Setup |
| `KeyError: GEMINI_API_KEY` on startup | Env var not set | Add it to the platform's environment / secrets settings |
| Render cold-start timeout | Free tier spun down | Upgrade to paid, or use Koyeb/Fly.io for always-on free hosting |
| `requests.HTTPError: 401` | Invalid or expired access token | Regenerate `WHATSAPP_ACCESS_TOKEN` |
