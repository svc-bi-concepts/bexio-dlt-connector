# Authentication — how this connector talks to bexio

This document describes **exactly** how credentials are obtained and how each HTTP call to `https://api.bexio.com/` is authorized.

**This repository supports OAuth (registered application) only.** Personal Access Tokens (`TOKEN`, `snowflake_connector_pat`, `BEXIO_TOKEN`) are **not** read or used.

---

## 1. What the API expects

Every request to the bexio API uses:

| Header | Value |
|--------|--------|
| `Accept` | `application/json` |
| `Content-Type` | `application/json` |
| `Authorization` | `Bearer <access_token>` |

The **access token** is always a **bearer** string. It is **not** the client secret. The client secret is only used **server-side** against the IdP token endpoint.

Official reference: [bexio API — Authentication](https://docs.bexio.com/#section/Authentication).

---

## 2. OAuth application (only supported mode)

bexio uses **OpenID Connect** on:

- **Token endpoint:** `https://auth.bexio.com/realms/bexio/protocol/openid-connect/token`
- **Authorization endpoint:** `https://auth.bexio.com/realms/bexio/protocol/openid-connect/auth`

This repo authenticates the pipeline as follows:

1. **On each pipeline run**, `bexio_credentials.resolve_bearer_token()` runs **before** any API fetch.
2. It reads **`BEXIO_CLIENT_ID`**, **`BEXIO_CLIENT_SECRET`**, and a **refresh token** (see §3).
3. It sends a **`grant_type=refresh_token`** request to the token URL (form body, not query string), with `client_id`, `client_secret`, and `refresh_token`.
4. The JSON response must contain **`access_token`**. That value is returned and wrapped in `Authorization: Bearer …` via `build_headers()`.
5. If the IdP returns a **new** `refresh_token`, it is persisted when **`BEXIO_REFRESH_TOKEN_FILE`** is set (see §4). Otherwise an INFO log reminds you to configure persistence.

If refresh credentials are missing, the resolver may fall back to **`BEXIO_ACCESS_TOKEN`** only (short-lived; see §6).

Code: `bexio_credentials.py` (resolve + headers), `bexio_oauth.py` (HTTP calls to the token URL).

---

## 3. Refresh token: environment vs file

`resolve_bearer_token()` loads the refresh token via `load_refresh_token_from_env_or_file()`:

| Source | Variable | Behavior |
|--------|-----------|----------|
| **File (preferred for rotation)** | `BEXIO_REFRESH_TOKEN_FILE` | If the path exists and the file has a non-empty first line, that value is used **before** the env var. |
| **Environment** | `BEXIO_REFRESH_TOKEN` | Used if the file is missing or empty. |

**Why file first:** after IdP rotation, the new refresh token is written to the file. A stale `BEXIO_REFRESH_TOKEN` still injected into the container environment would otherwise override the new token.

---

## 4. Automatic refresh-token rotation

When the token endpoint returns a **new** `refresh_token` (rotation), `persist_refresh_token_if_configured()`:

- If **`BEXIO_REFRESH_TOKEN_FILE`** is set to a **writable** path: writes the new token **atomically** (temp file + replace, file mode `0600` where supported) and logs success.
- If it is **not** set: logs that rotation occurred and that you should set the file path (or update your secret store yourself).

For Snowflake SPCS / Kubernetes, mount a **persistent volume** at that path so the next daily run reads the updated token without manual `.env` edits.

---

## 5. One-time setup: register the app and get the first refresh token

### 5.1 In the bexio developer portal

1. Open [developer.bexio.com](https://developer.bexio.com) → **My apps** → create (or edit) an app.
2. Set **Allowed redirect URL** to exactly what you will use locally, e.g. `http://127.0.0.1:8765/callback` (scheme, host, port, and path must match **character for character** later in `.env`).
3. Save and copy **Client ID** and **Client Secret**.

### 5.2 In `.env` (or container env)

```env
BEXIO_CLIENT_ID=...
BEXIO_CLIENT_SECRET=...
BEXIO_REDIRECT_URI=http://127.0.0.1:8765/callback
# Optional: space-separated scopes (default in code is a broad read set; see oauth_login.py DEFAULT_BEXIO_READ_SCOPES)
# BEXIO_SCOPES=openid offline_access ...
```

### 5.3 Run the login helper (once per consent / scope change)

From the repository root:

```bash
python oauth_login.py
```

What it does:

1. Builds the authorization URL (`response_type=code`, `scope`, `state`, `redirect_uri`).
2. Opens a browser (or prints the URL).
3. Listens on the **host and port parsed from `BEXIO_REDIRECT_URI`** for one GET with `?code=…`.
4. Exchanges **`code`** for tokens at the token endpoint (`grant_type=authorization_code`, plus `client_id`, `client_secret`, `redirect_uri`).
5. Prints **`BEXIO_ACCESS_TOKEN`** and **`BEXIO_REFRESH_TOKEN`** — store the refresh token in your secret manager / `.env` / mounted file (never commit).

If `BEXIO_REFRESH_TOKEN_FILE` is set, the script also writes the initial refresh token to that file.

---

## 6. Short-lived access token only (`BEXIO_ACCESS_TOKEN`)

Used only when **refresh credentials are not configured** but you need a quick run (e.g. right after `oauth_login.py` before you persist the refresh token), or for a very short test.

Set **`BEXIO_ACCESS_TOKEN`** to the access token string from the login response. It **expires** quickly; production and daily jobs must use **refresh token + client id + secret** (and ideally `BEXIO_REFRESH_TOKEN_FILE` for rotation).

---

## 7. End-to-end flow (pipeline run)

```
resolve_bearer_token()
  → refresh grant (preferred) OR BEXIO_ACCESS_TOKEN fallback
  → access_token string
build_headers(access_token)
  → { Authorization: Bearer <access_token>, Accept: application/json, … }

Each GET https://api.bexio.com/<path> uses those headers.
```

Implementation entrypoint: `dlt_pipeline.py` calls `resolve_bearer_token()` once per run, then passes the same headers into every endpoint fetch.

---

## 8. Scopes and user rights (bexio rules)

- **Scopes** are granted on the OAuth consent screen; they limit what the **application** may do.
- **User rights** in the bexio UI limit what the **connecting user** may do.

Both must allow an endpoint or the API returns **403** (this connector logs some 403s as skipped endpoints and continues).

---

## 9. Related files

| File | Role |
|------|------|
| `bexio_credentials.py` | Resolve bearer token; build API headers. |
| `bexio_oauth.py` | Token URL; refresh + authorization-code exchange; load/save refresh token file. |
| `oauth_login.py` | Browser-based first login; prints tokens; optional initial file write. |
| `dlt_pipeline.py` | Calls `resolve_bearer_token()` then calls the API with `build_headers()`. |

---

## 10. Security checklist

- Never commit `.env`, client secrets, or refresh tokens.
- Use **OAuth + refresh file or secret store** for production schedules.
- Use **least-privilege** `BEXIO_SCOPES` if you tighten scopes beyond the default in `oauth_login.py`.
