"""Shared HTTP session with retries and a polite User-Agent."""

from __future__ import annotations

import logging

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from . import config

log = logging.getLogger(__name__)


def _build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": config.USER_AGENT})
    retry = Retry(
        total=3,
        backoff_factor=1.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET"]),
        respect_retry_after_header=True,
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.mount("http://", HTTPAdapter(max_retries=retry))
    return session


SESSION = _build_session()


def get(url: str, **kwargs) -> requests.Response | None:
    """GET a URL, returning None instead of raising so one dead source can't
    take down the whole run."""
    kwargs.setdefault("timeout", 30)
    try:
        response = SESSION.get(url, **kwargs)
        response.raise_for_status()
        return response
    except requests.RequestException as exc:
        log.warning("request failed: %s (%s)", url, exc)
        return None
