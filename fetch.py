"""Polite HTTP: robots.txt respected, per-host rate limit, on-disk cache.

Pages that answer with a bot challenge (e.g. HTTP 202/403 interstitials) are
reported and skipped; nothing here tries to get around bot protection.
"""
import hashlib
import json
import time
import urllib.robotparser
from pathlib import Path
from urllib.parse import urlparse

import requests

import config

CACHE = Path(__file__).parent / "output" / "cache"
CACHE.mkdir(parents=True, exist_ok=True)

_session = requests.Session()
_session.headers.update({
    # A browser-style UA with our identifier appended: several Indian OTAs
    # serve an empty shell to unknown agents, but we still say who we are.
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/128.0 Safari/537.36 " + config.USER_AGENT,
    "Accept-Language": "en-IN,en;q=0.9",
})
_last_hit: dict[str, float] = {}
last_status = None  # HTTP status of the most recent network request
_robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}


def _allowed(url: str) -> bool:
    host = urlparse(url).scheme + "://" + urlparse(url).netloc
    if host not in _robots:
        rp = urllib.robotparser.RobotFileParser()
        try:
            r = _session.get(host + "/robots.txt", timeout=20)
            rp.parse(r.text.splitlines() if r.ok else [])
            _robots[host] = rp
        except requests.RequestException:
            _robots[host] = None
    rp = _robots[host]
    return True if rp is None else rp.can_fetch(config.USER_AGENT, url)


def get(url: str, *, method="GET", data=None, json_body=None, headers=None,
        use_cache=True, check_robots=True, min_bytes=500) -> str | None:
    key = hashlib.sha1(json.dumps([method, url, data, json_body]).encode()).hexdigest()
    path = CACHE / key
    if use_cache and path.exists():
        return path.read_text(encoding="utf-8")
    if check_robots and not _allowed(url):
        print(f"  [robots] disallowed: {url}")
        return None
    host = urlparse(url).netloc
    wait = config.REQUEST_DELAY_S - (time.time() - _last_hit.get(host, 0))
    if wait > 0:
        time.sleep(wait)
    try:
        r = _session.request(method, url, data=data, json=json_body, headers=headers,
                             timeout=200, allow_redirects=True)
    except requests.RequestException as e:
        print(f"  [error] {url}: {e}")
        return None
    finally:
        _last_hit[host] = time.time()
    global last_status
    last_status = r.status_code
    if r.status_code != 200 or len(r.content) < min_bytes:
        print(f"  [skip] HTTP {r.status_code} ({len(r.content)} bytes): {url}")
        if "json" in r.headers.get("content-type", ""):
            print("         " + r.text[:300].replace("\n", " "))
        return None
    path.write_text(r.text, encoding="utf-8")
    return r.text
