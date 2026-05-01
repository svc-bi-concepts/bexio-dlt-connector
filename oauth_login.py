"""
One-time OAuth login: opens browser, captures authorization code on localhost,
prints access + refresh token (store refresh token securely for scheduled jobs).

Requires in .env (or environment):
  BEXIO_CLIENT_ID, BEXIO_CLIENT_SECRET, BEXIO_REDIRECT_URI, BEXIO_SCOPES

Register the same redirect URI in https://developer.bexio.com for your app.
"""

from __future__ import annotations

import os
import secrets
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

from dotenv import load_dotenv

from bexio_oauth import (
    build_authorization_redirect,
    exchange_authorization_code,
    persist_refresh_token_if_configured,
)

load_dotenv()

# Default: all documented read-style API scopes + OIDC (no *_edit / stock_edit).
# `accounting` is the only scope listed for accounting APIs (journal, accounts, …);
# bexio labels it "Write access" but there is no separate accounting_show in the public table.
# `file` is the scope for inbox/files (docs: read and write to inbox).
DEFAULT_BEXIO_READ_SCOPES = (
    "openid offline_access profile email company_profile "
    "accounting "
    "article_show bank_account_show bank_payment_show contact_show file "
    "kb_invoice_show kb_offer_show kb_order_show kb_delivery_show "
    "monitoring_show note_show kb_article_order_show project_show task_show "
    "kb_bill_show kb_expense_show "
    "payroll_employee_show payroll_absence_show payroll_paystub_show"
)


class _CallbackHandler(BaseHTTPRequestHandler):
    code: str | None = None
    error: str | None = None
    expected_state: str = ""

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        if "error" in qs:
            _CallbackHandler.error = qs["error"][0]
        elif "code" in qs:
            state = qs.get("state", [""])[0]
            if state != _CallbackHandler.expected_state:
                _CallbackHandler.error = "state_mismatch"
            else:
                _CallbackHandler.code = qs["code"][0]
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        if _CallbackHandler.code:
            self.wfile.write(b"OK. You can close this tab.")
        else:
            self.wfile.write(b"Login failed. Check the terminal.")

    def log_message(self, format: str, *args: object) -> None:  # noqa: A003
        return


def main() -> None:
    client_id = os.environ.get("BEXIO_CLIENT_ID")
    client_secret = os.environ.get("BEXIO_CLIENT_SECRET")
    redirect_uri = os.environ.get("BEXIO_REDIRECT_URI")
    scope = os.environ.get("BEXIO_SCOPES", DEFAULT_BEXIO_READ_SCOPES)
    if not (client_id and client_secret and redirect_uri):
        raise SystemExit(
            "Set BEXIO_CLIENT_ID, BEXIO_CLIENT_SECRET, and BEXIO_REDIRECT_URI "
            "(e.g. http://127.0.0.1:8765/callback)."
        )
    state = secrets.token_urlsafe(16)
    _CallbackHandler.expected_state = state
    url, _ = build_authorization_redirect(
        client_id=client_id,
        redirect_uri=redirect_uri,
        scope=scope,
        state=state,
    )
    parsed = urlparse(redirect_uri)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 8765
    server = HTTPServer((host, port), _CallbackHandler)
    print("Opening browser. If it does not open, visit:\n", url, sep="")
    webbrowser.open(url)
    server.handle_request()
    if _CallbackHandler.error:
        raise SystemExit(f"OAuth error: {_CallbackHandler.error}")
    if not _CallbackHandler.code:
        raise SystemExit("No authorization code received.")
    tokens = exchange_authorization_code(
        client_id=client_id,
        client_secret=client_secret,
        code=_CallbackHandler.code,
        redirect_uri=redirect_uri,
    )
    print("\n--- Store these as secrets (never commit) ---")
    print("BEXIO_ACCESS_TOKEN=", tokens.get("access_token", ""), sep="")
    print("BEXIO_REFRESH_TOKEN=", tokens.get("refresh_token", ""), sep="")
    print("\nFor daily jobs, persist BEXIO_REFRESH_TOKEN in a secret store and set")
    print("BEXIO_CLIENT_ID / BEXIO_CLIENT_SECRET and either BEXIO_REFRESH_TOKEN or BEXIO_REFRESH_TOKEN_FILE.")
    rt = tokens.get("refresh_token") or ""
    if rt and os.environ.get("BEXIO_REFRESH_TOKEN_FILE", "").strip():
        persist_refresh_token_if_configured(rt, "")
        print("Wrote refresh token to BEXIO_REFRESH_TOKEN_FILE.")


if __name__ == "__main__":
    main()
