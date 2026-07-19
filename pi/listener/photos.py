"""Keep a local copy of the family photo album (Supabase Storage).

The Pi runs on metered 4G, so photos are cached on disk and only what's
actually missing is downloaded — a slideshow loop never re-fetches anything.
Deletions propagate too, so removing a photo from the app removes it here.

Stdlib only (same approach as supa_auth.py); blocking, so call it from
asyncio via asyncio.to_thread.
"""

import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request

logger = logging.getLogger("visio-tv.photos")

BUCKET = "photos"
LIST_PAGE_SIZE = 100
# Anything else in the bucket is ignored rather than downloaded blindly.
ALLOWED_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp", ".gif")


def _request(url: str, anon_key: str, token: str, method: str = "GET", body=None):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"apikey": anon_key, "Authorization": f"Bearer {token}"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    return urllib.request.urlopen(req, timeout=30)


def list_remote(supabase_url: str, anon_key: str, token: str) -> list[str] | None:
    """Names of the photos in the bucket, or None if the listing failed."""
    url = f"{supabase_url.rstrip('/')}/storage/v1/object/list/{BUCKET}"
    names: list[str] = []
    offset = 0
    try:
        while True:
            body = {
                "prefix": "",
                "limit": LIST_PAGE_SIZE,
                "offset": offset,
                "sortBy": {"column": "name", "order": "asc"},
            }
            with _request(url, anon_key, token, "POST", body) as resp:
                page = json.loads(resp.read())
            if not isinstance(page, list):
                logger.warning("Unexpected listing payload: %r", page)
                return None
            for item in page:
                name = item.get("name")
                # Supabase lists a placeholder row for empty folders.
                if name and name.lower().endswith(ALLOWED_SUFFIXES):
                    names.append(name)
            if len(page) < LIST_PAGE_SIZE:
                return names
            offset += LIST_PAGE_SIZE
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        logger.warning("Could not list photos: %s", e)
        return None


def _download(supabase_url: str, anon_key: str, token: str, name: str, dest: str) -> bool:
    url = (
        f"{supabase_url.rstrip('/')}/storage/v1/object/{BUCKET}/"
        f"{urllib.parse.quote(name)}"
    )
    tmp = dest + ".part"
    try:
        with _request(url, anon_key, token) as resp, open(tmp, "wb") as f:
            while chunk := resp.read(64 * 1024):
                f.write(chunk)
        os.replace(tmp, dest)  # atomic: imv never sees a half-written file
        return True
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        logger.warning("Failed to download %s: %s", name, e)
        try:
            os.unlink(tmp)
        except OSError:
            pass
        return False


def sync(supabase_url: str, anon_key: str, token: str, dest_dir: str) -> tuple[int, int]:
    """Mirror the bucket into dest_dir. Returns (downloaded, removed).

    Only missing files are fetched, so repeated calls are nearly free.
    """
    remote = list_remote(supabase_url, anon_key, token)
    if remote is None:
        return (0, 0)  # leave the existing cache untouched on failure

    os.makedirs(dest_dir, exist_ok=True)
    local = {
        f
        for f in os.listdir(dest_dir)
        if f.lower().endswith(ALLOWED_SUFFIXES) and os.path.isfile(os.path.join(dest_dir, f))
    }
    remote_set = set(remote)

    downloaded = 0
    for name in remote_set - local:
        if _download(supabase_url, anon_key, token, name, os.path.join(dest_dir, name)):
            downloaded += 1

    removed = 0
    for name in local - remote_set:
        try:
            os.unlink(os.path.join(dest_dir, name))
            removed += 1
        except OSError as e:
            logger.warning("Failed to remove %s: %s", name, e)

    if downloaded or removed:
        logger.info("Photo sync: +%s -%s (%s total)", downloaded, removed, len(remote_set))
    return (downloaded, removed)


def count_local(dest_dir: str) -> int:
    try:
        return sum(1 for f in os.listdir(dest_dir) if f.lower().endswith(ALLOWED_SUFFIXES))
    except OSError:
        return 0
