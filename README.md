# Integration Microservice — HubSpot CRM

A standalone backend microservice that integrates with **HubSpot's free CRM**
(Contacts, Companies, Deals) via a public OAuth2 app. It authenticates with
HubSpot, syncs CRM data into a local database, receives real-time updates via
webhooks, and exposes its own clean REST API on top of the local data.

## Why HubSpot

HubSpot's free CRM tier was chosen over the other common free-tier options
because it's the only one that offers, at no cost:

- **Full OAuth2 with refresh tokens** (not just a static API key/private-app
  token) — a public OAuth app on HubSpot's free developer platform gets a
  real authorization-code grant with 30-minute access tokens and long-lived
  refresh tokens.
- **App-level webhooks on the free tier** — no paid Hub subscription
  required to receive `creation`/`propertyChange`/`deletion` events.
- **A rich, realistic multi-object data model** (Contacts, Companies, Deals,
  with associations between them) that maps naturally onto a real CRM
  integration, rather than a single flat resource.

## Architecture at a glance

```
Client → API layer (FastAPI) → Orchestration engine → HubSpot adapter → HubSpot API
                                       ↓
                                  Local database
```

- **API layer** (`app/api/`) — thin FastAPI routers; no business logic, no
  direct calls to HubSpot.
- **Orchestration engine** (`app/orchestration/`) — token lifecycle (proactive
  refresh), rate limiting, retry/backoff, sync and webhook processing. Only
  layer that coordinates across the adapter and the database.
- **Provider adapter** (`app/adapters/hubspot/`) — the only code that knows
  HubSpot's specific endpoints, auth flow, and webhook signature format,
  behind a small `ProviderAdapter` interface. Adding a second provider (e.g.
  Salesforce) means writing one new adapter, not touching the engine.
- **Database** (`app/db/`) — SQLAlchemy models + repository functions on top
  of SQLite (swappable to Postgres via `DATABASE_URL`).

## Setup

### 1. Prerequisites

- Python 3.12+
- A free HubSpot account, a free HubSpot **developer** account, and a
  developer **test account** created inside it (all free — see
  [HubSpot's developer docs](https://developers.hubspot.com/) for account
  setup)
- The [HubSpot CLI](https://developers.hubspot.com/docs/guides/other-resources/tools/cli)
  (`npm install -g @hubspot/cli@latest`) to create and configure the OAuth
  app
- [ngrok](https://ngrok.com/) (or similar) if you want to receive real
  webhook deliveries during local development

### 2. Install dependencies

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows
# source .venv/bin/activate       # macOS/Linux
pip install -e ".[dev]"
```

### 3. Create the HubSpot app

1. `hs account auth` — authenticate the CLI against your developer account.
2. `hs project create` → choose **App**, `--distribution private`,
   `--auth oauth`, and enable the **Webhooks** feature.
3. In the generated project's `app-hsmeta.json`, set the redirect URL to
   `http://localhost:8000/oauth/callback` and the required scopes to:
   ```json
   ["oauth",
    "crm.objects.contacts.read", "crm.objects.contacts.write",
    "crm.objects.companies.read", "crm.objects.companies.write",
    "crm.objects.deals.read", "crm.objects.deals.write"]
   ```
4. `hs project upload` to deploy the app, then `hs project open` → the app's
   **Auth** tab → copy the **Client ID** and **Client Secret**.

### 4. Configure environment variables

Copy `.env.example` to `.env` and fill in your values:

| Variable | Required | Description |
|---|---|---|
| `HUBSPOT_CLIENT_ID` | Yes | From the app's Auth tab |
| `HUBSPOT_CLIENT_SECRET` | Yes | From the app's Auth tab — never commit this |
| `HUBSPOT_REDIRECT_URI` | Yes | Must match the app's configured redirect URL exactly (default `http://localhost:8000/oauth/callback`) |
| `DATABASE_URL` | Yes | SQLite by default (`sqlite+aiosqlite:///./local.db`); any Postgres URL works too |
| `APP_BASE_URL` | Yes, for webhooks | The public URL this service is reachable at — must match the ngrok URL you configure as the webhook `targetUrl` (see below). HubSpot signs webhook requests against this full URL, not just the request path. |
| `HTTPX_VERIFY_SSL` | No (default `true`) | Set to `false` **only** if you're on a network with a TLS-inspecting corporate proxy (e.g. Netskope/Zscaler) that breaks certificate verification for outbound HTTPS calls. Never disable this outside local dev. |

### 5. Run database migrations

```bash
alembic upgrade head
```

### 6. Start the server

```bash
uvicorn app.main:app --port 8000
```

Visit `http://localhost:8000/health` to confirm it's running.

### 6a. Or run it with Docker

Skips steps 2, 5, and 6 above — the container installs dependencies and runs
migrations automatically on startup:

```bash
docker compose up --build
```

This builds the image, runs `alembic upgrade head`, and starts the API on
`http://localhost:8000`, backed by a named Docker volume (`sqlite_data`) so
data survives container restarts. Requires `.env` to already exist (step 4).

### 7. (Optional) Wire up webhooks

Webhooks require a public HTTPS URL — `localhost` won't work.

1. `ngrok http 8000`, copy the `https://...ngrok-free.app` URL.
2. Set `APP_BASE_URL` in `.env` to that URL, and restart the server.
3. In the HubSpot project's `webhooks-hsmeta.json`, set `targetUrl` to
   `<your-ngrok-url>/webhook`, then `hs project upload`.
4. Make a change in HubSpot (edit a contact's email, create a deal, etc.) and
   confirm it lands in the local `webhook_events` table within a few
   seconds.

## Authenticating and running a sync

### Install (OAuth flow)

Open this URL in a browser:

```
http://localhost:8000/oauth/authorize
```

This redirects to HubSpot's consent screen. After you approve, HubSpot
redirects back to `/oauth/callback`, which exchanges the authorization code
for tokens and stores them keyed by `hub_id` (HubSpot's portal ID — this is
your tenant identifier for every other endpoint below):

```json
{"status": "installed", "hub_id": "12345678"}
```

### Run a sync

```bash
curl -X POST http://localhost:8000/sync \
  -H "Content-Type: application/json" \
  -d '{"hub_id": "12345678"}'
```

Optionally sync only specific object types:

```bash
curl -X POST http://localhost:8000/sync \
  -H "Content-Type: application/json" \
  -d '{"hub_id": "12345678", "object_types": ["contacts", "deals"]}'
```

Response — one entry per synced object type:

```json
[
  {"object_type": "contacts", "status": "completed", "records_fetched": 2, "records_upserted": 2, "records_failed": 0},
  {"object_type": "deals", "status": "completed", "records_fetched": 0, "records_upserted": 0, "records_failed": 0}
]
```

Re-running `/sync` is idempotent — records are upserted by HubSpot object
ID, never duplicated.

## API reference

### `GET /oauth/authorize`
Redirects to HubSpot's OAuth consent screen. No parameters.

### `GET /oauth/callback`
OAuth redirect target — not called directly. Returns `{"status": "installed", "hub_id": "..."}`.

### `POST /sync`
Fetches contacts/companies/deals from HubSpot (paginated, rate-limited,
retried on 429/5xx) and upserts them into the local database.

```bash
curl -X POST http://localhost:8000/sync \
  -H "Content-Type: application/json" \
  -d '{"hub_id": "12345678"}'
```

| Body field | Required | Description |
|---|---|---|
| `hub_id` | Yes | The installed portal's HubSpot ID, from the OAuth callback response |
| `object_types` | No | List of `contacts`/`companies`/`deals`; defaults to all three |

### `POST /webhook`
Receives HubSpot webhook events (called by HubSpot, not directly by clients).
Verifies the `X-HubSpot-Signature-v3` HMAC signature before doing anything
else; on success, persists every event and processes it in the background
(re-fetches the object and upserts it — same code path as `/sync`).

### `GET /contacts`, `GET /companies`, `GET /deals`
Read from the local database only — never call out to HubSpot. Support
filtering by any promoted property and sorting.

```bash
# Filter contacts by email
curl "http://localhost:8000/contacts?email=jane@example.com"

# Sort deals by most recently updated, limit results
curl "http://localhost:8000/deals?sort=-updated_at&limit=10"

# Filter companies by domain
curl "http://localhost:8000/companies?domain=acme.com"
```

| Endpoint | Filterable fields | Sortable fields |
|---|---|---|
| `/contacts` | `email`, `firstname`, `lastname`, `lifecyclestage` | those, plus `created_at`, `updated_at` |
| `/companies` | `name`, `domain` | those, plus `created_at`, `updated_at` |
| `/deals` | `dealname`, `dealstage`, `amount`, `pipeline` | those, plus `created_at`, `updated_at` |

Common query params on all three: `sort` (prefix with `-` for descending,
e.g. `-updated_at`), `limit` (default 50, max 100), `offset` (default 0).

### Error responses

Every error (from HubSpot, or from this service's own validation) is mapped
to a consistent envelope — HubSpot's raw error shape is never returned
directly to the client:

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Cannot sort contacts by 'not_a_real_field'",
    "correlation_id": "a1b2c3d4-..."
  }
}
```

| HTTP status | `code` | Meaning |
|---|---|---|
| 400 | `VALIDATION_ERROR` | Malformed request (e.g. invalid filter/sort field, unknown object type) |
| 401 | `AUTHENTICATION_ERROR` / `TOKEN_REFRESH_FAILED` | Invalid OAuth state, or a refresh token that HubSpot has revoked |
| 404 | `NOT_FOUND` | No install found for the given `hub_id` |
| 409 | `CONFLICT` | Duplicate unique property on a HubSpot write |
| 429 | `RATE_LIMITED` | HubSpot's rate limit was hit and retries were exhausted |
| 502 | `UPSTREAM_UNAVAILABLE` | HubSpot returned a 5xx or was unreachable |

## Design decisions and trade-offs

- **Provider-adapter pattern.** All HubSpot-specific logic (endpoints, auth,
  webhook signatures) lives behind a small `ProviderAdapter` interface. The
  orchestration engine, database schema, and API layer never import a
  concrete adapter class directly — they resolve one via a small registry
  function. This is what makes a second integration (Salesforce, Slack, …)
  additive rather than a rewrite.
- **Proactive token refresh, not reactive.** Access tokens are refreshed
  before they expire (at 80% of their 30-minute lifetime), not in response
  to a 401 — per HubSpot's own guidance that a 401 isn't a reliable signal
  to refresh.
- **Idempotency via `(install, hubspot_object_id)`**, not HubSpot's
  upsert-by-property pattern. One dedup rule applies uniformly whether a
  record arrives via `/sync` or a webhook.
- **One table per object type** (`contacts`, `companies`, `deals`) rather
  than a single polymorphic table, so filtering/sorting can use real indexed
  columns instead of JSON-path queries. Each row also stores the full raw
  `properties` blob for flexibility.
- **Engine-enforced, adapter-configured rate limiting.** A token-bucket
  limiter throttles proactively (below HubSpot's documented 110 req/10s),
  separate from the retry-on-429 logic — so most requests never hit a real
  rate limit in the first place.
- **`BackgroundTasks` for webhook processing**, not a separate queue worker.
  Keeps the infrastructure footprint small for this project's scope; the
  seam between "receive and persist" and "process" is the same one a real
  queue (Celery/RQ) would occupy, so upgrading later is additive.
- **Webhook signature verification against the full public URL.** HubSpot
  signs the external URL it was configured to POST to (`APP_BASE_URL` +
  path), not the path the server sees internally — this matters whenever
  the service sits behind a tunnel or reverse proxy.
- **Errors are always remapped**, never passed through raw. HubSpot's error
  shape is internal detail; clients of this API see one consistent envelope
  regardless of what went wrong upstream.

## Testing

```bash
pytest
```

55 tests cover: OAuth token exchange/refresh (mocked HTTP via `respx`),
pagination and error mapping in the CRM adapter, retry/backoff behavior with
a fake adapter, rate-limiter throttling, idempotent upserts, webhook
signature verification (valid/tampered/stale/wrong-secret), and full
API-level flows (`/sync`, `/webhook`, `/contacts`) via FastAPI's `TestClient`
with dependency-injected fakes — no test ever calls the real HubSpot API.
