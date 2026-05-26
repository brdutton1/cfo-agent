"""
OAuth 2.0 lifecycle for QBO. Handles first-run interactive auth, token
storage, and silent refresh on subsequent runs.

Token file schema:
  {
    "access_token": "...",
    "refresh_token": "...",
    "expires_at": "2026-05-25T10:00:00",   # ISO 8601 UTC
    "realm_id": "..."
  }
"""

import json
import os
import sys
import time
import urllib.parse
from datetime import datetime, timezone, timedelta
from base64 import b64encode

import requests

from .config import Config

_TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
_AUTH_URL = "https://appcenter.intuit.com/connect/oauth2"
_SCOPES = "com.intuit.quickbooks.accounting com.intuit.quickbooks.banking"
_REFRESH_BUFFER_SECONDS = 300  # refresh 5 minutes before expiry


class AuthError(Exception):
    pass


def _load_tokens(path: str) -> dict | None:
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


def _save_tokens(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def _basic_auth_header(client_id: str, client_secret: str) -> str:
    creds = b64encode(f"{client_id}:{client_secret}".encode()).decode()
    return f"Basic {creds}"


def _exchange_code(config: Config, code: str) -> dict:
    resp = requests.post(
        _TOKEN_URL,
        headers={
            "Authorization": _basic_auth_header(config.client_id, config.client_secret),
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": config.redirect_uri,
        },
        timeout=15,
    )
    if not resp.ok:
        raise AuthError(f"Token exchange failed ({resp.status_code}): {resp.text}")
    return resp.json()


def _refresh_access_token(config: Config, refresh_token: str) -> dict:
    resp = requests.post(
        _TOKEN_URL,
        headers={
            "Authorization": _basic_auth_header(config.client_id, config.client_secret),
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
        timeout=15,
    )
    if not resp.ok:
        raise AuthError(f"Token refresh failed ({resp.status_code}): {resp.text}")
    return resp.json()


def _is_expired(tokens: dict) -> bool:
    expires_at_str = tokens.get("expires_at")
    if not expires_at_str:
        return True
    expires_at = datetime.fromisoformat(expires_at_str).replace(tzinfo=timezone.utc)
    cutoff = datetime.now(timezone.utc) + timedelta(seconds=_REFRESH_BUFFER_SECONDS)
    return cutoff >= expires_at


def _first_run_auth(config: Config) -> dict:
    """Interactive OAuth flow for first-time setup."""
    params = {
        "client_id": config.client_id,
        "scope": _SCOPES,
        "redirect_uri": config.redirect_uri,
        "response_type": "code",
        "state": "bookkeeper",
    }
    auth_url = f"{_AUTH_URL}?{urllib.parse.urlencode(params)}"

    print("\n--- QBO First-Run Authorization ---")
    print("Open this URL in your browser and approve access to your QBO company:\n")
    print(f"  {auth_url}\n")
    print("After approval, you will be redirected. Copy the full redirect URL")
    print("(or just the 'code' parameter) and paste it here:")
    raw = input("> ").strip()

    # Accept either the full URL or just the code value
    if raw.startswith("http"):
        parsed = urllib.parse.urlparse(raw)
        params_parsed = urllib.parse.parse_qs(parsed.query)
        code = params_parsed.get("code", [None])[0]
        realm_id = params_parsed.get("realmId", [config.realm_id])[0]
    else:
        code = raw
        realm_id = config.realm_id

    if not code:
        raise AuthError("Could not extract authorization code from input.")

    token_data = _exchange_code(config, code)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=token_data["expires_in"])

    tokens = {
        "access_token": token_data["access_token"],
        "refresh_token": token_data["refresh_token"],
        "expires_at": expires_at.isoformat(),
        "realm_id": realm_id,
    }
    _save_tokens(config.token_file, tokens)
    print(f"Tokens saved to {config.token_file}\n")
    return tokens


def get_valid_token(config: Config) -> str:
    """Return a valid access token, refreshing or doing first-run auth as needed."""
    tokens = _load_tokens(config.token_file)

    if tokens is None:
        tokens = _first_run_auth(config)
        return tokens["access_token"]

    if _is_expired(tokens):
        refresh_token = tokens.get("refresh_token")
        if not refresh_token:
            raise AuthError("No refresh token available. Delete the token file and re-authorize.")
        token_data = _refresh_access_token(config, refresh_token)
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=token_data["expires_in"])
        tokens["access_token"] = token_data["access_token"]
        # QBO may rotate the refresh token; always save the latest one
        tokens["refresh_token"] = token_data.get("refresh_token", refresh_token)
        tokens["expires_at"] = expires_at.isoformat()
        _save_tokens(config.token_file, tokens)

    return tokens["access_token"]
