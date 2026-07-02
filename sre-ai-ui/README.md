# SRE AI UI

A Next.js chat interface for interacting with ADK-based SRE agents (health checks, pod status, deployment rollouts, etc.).

---

## Prerequisites

- **Node.js** 20+
- **npm**
- An ADK agent backend running (default: `http://localhost:8010`)

---

## Running Locally

### 1. Install dependencies

```bash
npm install
```

### 2. Create `.env.local`

Copy the template below into a new file called `.env.local` in the project root and fill in your values:

```env
# ─── ADK Agents ───────────────────────────────────────────────────────────────
# JSON array of agent definitions.
# Required fields per entry: id, name, url
# Optional fields: emoji, description
ADK_AGENTS='[{"id":"health","name":"Health Agent","url":"http://localhost:8010/a2a","emoji":"🏥","description":"Namespace health, pod status, and deployment rollouts"}]'

# Base URL for the ADK agent backend (used by sessions and messages APIs)
ADK_AGENT_BASE_URL=http://localhost:8010

# ─── PingFederate SSO ─────────────────────────────────────────────────────────
# OAuth2 client credentials registered in PingFed for this app
PINGFED_CLIENT_ID=your-client-id
PINGFED_CLIENT_SECRET=your-client-secret

# Callback URL — must match exactly what is registered in PingFed
PINGFED_REDIRECT_URI=http://localhost:3000/

# PingFed endpoint URLs (swap host for dev / cert / prod — see table below)
PINGFED_AUTH_URL=https://pfeddev.wal-mart.com/as/authorization.oauth2
PINGFED_TOKEN_URL=https://pfeddev.wal-mart.com/as/token.oauth2
PINGFED_USERINFO_URL=https://pfeddev.wal-mart.com/idp/userinfo.openid
PINGFED_LOGOUT_URL=https://pfeddev.wal-mart.com/idp/startSLO.ping

# OAuth2 scopes to request (default: openid profile email)
PINGFED_SCOPE=openid profile email

# ─── App ──────────────────────────────────────────────────────────────────────
# Base URL of this app — used for auth redirects
NEXTAUTH_URL=http://localhost:3000
```

### 3. Start the dev server

```bash
npm run dev
```

App will be available at **http://localhost:3000**

---

## Environment Variable Reference

| Variable | Required | Description |
|---|---|---|
| `ADK_AGENTS` | Yes | JSON array of agent configs (`id`, `name`, `url`, optional `emoji`/`description`) |
| `ADK_AGENT_BASE_URL` | Yes | Base URL of the ADK agent backend |
| `PINGFED_CLIENT_ID` | Yes | PingFed OAuth2 client ID |
| `PINGFED_CLIENT_SECRET` | Yes | PingFed OAuth2 client secret |
| `PINGFED_REDIRECT_URI` | Yes | OAuth2 callback URL — must match PingFed app registration |
| `PINGFED_AUTH_URL` | Yes | PingFed authorization endpoint |
| `PINGFED_TOKEN_URL` | Yes | PingFed token endpoint |
| `PINGFED_USERINFO_URL` | Yes | PingFed userinfo endpoint |
| `PINGFED_LOGOUT_URL` | No | PingFed single logout URL |
| `PINGFED_SCOPE` | No | OAuth2 scopes (default: `openid profile email`) |
| `NEXTAUTH_URL` | No | App base URL for redirects (default: `http://localhost:3000`) |

### PingFed environment hosts

| Environment | Host |
|---|---|
| dev | `pfeddev.wal-mart.com` |
| cert | `pfedcert.wal-mart.com` |
| prod | `pfedsso.wal-mart.com` |

> **Note:** If you hit auth redirect issues, confirm `PINGFED_REDIRECT_URI` in `.env.local` matches exactly what is registered in PingFed for your client ID.

---

## Other Commands

```bash
# Production build
npm run build
npm start

# Linting
npm run lint

# Tests
npm test                    # run all tests
npm run test:watch          # watch mode
npm run test:coverage       # with coverage report
npm run test:update-snapshots  # update Jest snapshots
```
