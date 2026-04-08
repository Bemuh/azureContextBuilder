"""Azure DevOps HTTP layer for story_context.

Forked from sync/ado.py and utils/fileOperations/PATOperations.py.
Isolated: no imports from sync or utils packages.
"""
from __future__ import annotations

import base64
import json
import os
import time
from typing import Iterable

import requests
from cryptography.fernet import Fernet

from .config import StoryContextError
from .utils import chunked

# ---------------------------------------------------------------------------
# PAT decryption — forked from utils/fileOperations/PATOperations.py
# Keys resolved package-relative so the folder can be moved freely.
# ---------------------------------------------------------------------------

_PACKAGE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_KEY_FILE = os.path.join(_PACKAGE_DIR, "keys", "encryption.key")
_TOKEN_FILE = os.path.join(_PACKAGE_DIR, "keys", "patToken.enc")


def _decrypt_pat() -> str:
    if not os.path.exists(_KEY_FILE):
        raise StoryContextError(
            f"Encryption key not found at '{_KEY_FILE}'. "
            "Run 'py -m sync setup' to create your PAT, then retry."
        )
    if not os.path.exists(_TOKEN_FILE):
        raise StoryContextError(
            f"PAT token not found at '{_TOKEN_FILE}'. "
            "Run 'py -m sync setup' to create your PAT, then retry."
        )
    with open(_KEY_FILE, "rb") as fh:
        key = fh.read()
    cipher = Fernet(key)
    with open(_TOKEN_FILE, "rb") as fh:
        encrypted = fh.read()
    return cipher.decrypt(encrypted).decode()


def _auth_headers(content_type: str = "application/json") -> dict:
    pat = _decrypt_pat()
    b64 = base64.b64encode(f":{pat}".encode()).decode()
    return {
        "Content-Type": content_type,
        "Authorization": f"Basic {b64}",
    }


def check_keys() -> None:
    """Verify PAT key files exist. Raises StoryContextError if missing."""
    if not os.path.exists(_KEY_FILE) or not os.path.exists(_TOKEN_FILE):
        raise StoryContextError(
            f"Keys not found at '{_KEY_FILE}' / '{_TOKEN_FILE}'. "
            "Run 'py -m sync setup' to create them."
        )


# ---------------------------------------------------------------------------
# HTTP session
# ---------------------------------------------------------------------------

class AdoError(Exception):
    pass


_session = requests.Session()
_session.trust_env = False  # bypass local proxy settings


def ado_request(
    url: str,
    method: str = "GET",
    payload=None,
    content_type: str | None = None,
    params=None,
    debug: int = 0,
) -> requests.Response:
    # Forked from sync/ado.py ado_request()
    headers = _auth_headers(content_type) if content_type else _auth_headers()
    method = method.upper()
    if debug > 0:
        print(f"\nADO {method} {url}")
        if payload is not None:
            try:
                preview = json.dumps(payload, indent=2, ensure_ascii=False, default=str)
            except TypeError:
                preview = str(payload)
            print(f"Payload:\n{preview}")
    response = _session.request(method, url, json=payload, headers=headers, params=params)
    if debug > 0 and response.status_code >= 400:
        print(f"ADO request failed: {response.status_code} - {response.text}")
    return response


# ---------------------------------------------------------------------------
# ADO API wrappers — forked from sync/ado.py
# ---------------------------------------------------------------------------

def wiql_query(organization: str, project: str, query: str, debug: int = 0) -> dict:
    url = (
        f"https://dev.azure.com/{organization}/{project}"
        f"/_apis/wit/wiql?api-version=7.1-preview.2"
    )
    response = ado_request(
        url, method="POST", payload={"query": query},
        content_type="application/json", debug=debug,
    )
    if response.status_code != 200:
        raise AdoError(f"WIQL query failed: {response.status_code} - {response.text}")
    return response.json()


def fetch_work_items(
    organization: str,
    ids: Iterable[int],
    fields: list[str],
    debug: int = 0,
) -> list[dict]:
    ids_str = ",".join(str(i) for i in ids)
    fields_str = ",".join(fields)
    url = (
        f"https://dev.azure.com/{organization}/_apis/wit/workitems"
        f"?ids={ids_str}&fields={fields_str}&api-version=7.1-preview.2"
    )
    response = ado_request(url, method="GET", debug=debug)
    if response.status_code != 200:
        raise AdoError(f"Work item fetch failed: {response.status_code} - {response.text}")
    return response.json().get("value", [])


def fetch_work_items_chunked(
    organization: str,
    ids: list[int],
    fields: list[str],
    chunk_size: int,
    debug: int = 0,
) -> list[dict]:
    """Fetch work items in chunks, auto-reducing chunk size on 413."""
    results: list[dict] = []
    if not ids:
        return results
    for batch in chunked(ids, chunk_size):
        current_size = len(batch)
        while current_size > 0:
            try:
                items = fetch_work_items(
                    organization, batch[:current_size], fields, debug=debug
                )
                results.extend(items)
                break
            except AdoError as exc:
                msg = str(exc)
                if "413" in msg or "too large" in msg or "request is too large" in msg:
                    current_size = max(1, current_size // 2)
                    if debug > 0:
                        print(f"Reducing chunk size to {current_size} due to 413.")
                    time.sleep(0.5)
                    continue
                raise
    return results


def fetch_work_item_with_relations(
    organization: str,
    story_id: int,
    debug: int = 0,
) -> dict:
    """Fetch a single work item with all its relation links expanded.

    Uses $expand=relations so parent/child links are available without
    a separate WIQL query per story.
    """
    url = (
        f"https://dev.azure.com/{organization}/_apis/wit/workitems/{story_id}"
        f"?$expand=relations&api-version=7.1-preview.3"
    )
    response = ado_request(url, method="GET", debug=debug)
    if response.status_code != 200:
        raise AdoError(
            f"Work item fetch (with relations) failed for #{story_id}: "
            f"{response.status_code} - {response.text}"
        )
    return response.json()
