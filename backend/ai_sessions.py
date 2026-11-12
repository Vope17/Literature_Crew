"""Temporary, browser-scoped AI settings. Secrets remain in server memory."""

import secrets
import time
from threading import Lock

COOKIE_NAME = "literature-ai-session"
SESSION_SECONDS = 8 * 60 * 60


class AISessions:
    def __init__(self):
        self.sessions = {}
        self.lock = Lock()

    def get(self, token):
        with self.lock:
            now = time.monotonic()
            self.sessions = {key: value for key, value in self.sessions.items() if value[0] > now}
            entry = self.sessions.get(token)
            return entry[1] if entry else None

    def set(self, token, settings):
        with self.lock:
            self.sessions.pop(token, None)
            token = secrets.token_urlsafe(32)
            self.sessions[token] = (time.monotonic() + SESSION_SECONDS, settings, secrets.token_urlsafe(16))
            return token

    def identifier(self, token):
        with self.lock:
            entry = self.sessions.get(token)
            return entry[2] if entry and entry[0] > time.monotonic() else "server"

    def clear(self):
        with self.lock:
            self.sessions.clear()
