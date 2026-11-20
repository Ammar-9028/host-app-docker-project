import hmac
import secrets
import threading
import time
from collections import defaultdict, deque

from flask import request, session


def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(24)
    return session["csrf"]


def csrf_ok():
    sent = request.form.get("csrf") or request.headers.get("X-CSRF-Token") or ""
    want = session.get("csrf") or ""
    return bool(want) and hmac.compare_digest(sent, want)


class RateLimiter:
    """Small in-memory sliding window limiter (per process)."""

    def __init__(self):
        self._hits = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key, limit, window):
        now = time.time()
        with self._lock:
            q = self._hits[key]
            while q and q[0] < now - window:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            return True
