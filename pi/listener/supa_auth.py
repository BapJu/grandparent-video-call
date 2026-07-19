"""Minimal Supabase (GoTrue) password login using only the stdlib.

Used by the listener to authenticate the Pi's dedicated device account so it
can join the private 'visio-tv-calls' Realtime channel.
"""

import json
import urllib.error
import urllib.request


class AuthError(RuntimeError):
    pass


def login(supabase_url: str, anon_key: str, email: str, password: str) -> dict:
    """Password-grant login. Returns the token payload
    ({access_token, refresh_token, expires_in, ...}). Raises AuthError on failure.

    Blocking (urllib) — call via asyncio.to_thread from async code.
    """
    url = f"{supabase_url.rstrip('/')}/auth/v1/token?grant_type=password"
    body = json.dumps({"email": email, "password": password}).encode()
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "apikey": anon_key,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            payload = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:300]
        raise AuthError(f"Supabase login failed: HTTP {e.code} {detail}") from e
    except (urllib.error.URLError, TimeoutError) as e:
        raise AuthError(f"Supabase login failed: {e}") from e

    if "access_token" not in payload:
        raise AuthError(f"Supabase login response missing access_token: {payload}")
    return payload
