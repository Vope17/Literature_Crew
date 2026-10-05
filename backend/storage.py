"""SQLite history and a PDF cache, using one connection per operation."""

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def timestamp():
    return datetime.now(timezone.utc).isoformat()


class HistoryStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS history (
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    topic TEXT NOT NULL,
                    model TEXT,
                    papers TEXT NOT NULL,
                    filters TEXT,
                    source TEXT,
                    notice TEXT,
                    status TEXT NOT NULL,
                    progress TEXT NOT NULL,
                    review TEXT,
                    evidence TEXT NOT NULL DEFAULT '[]',
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS history_created ON history(created_at DESC);
                CREATE TABLE IF NOT EXISTS pdfs (
                    id TEXT PRIMARY KEY,
                    url TEXT NOT NULL UNIQUE,
                    data BLOB NOT NULL,
                    created_at TEXT NOT NULL
                );
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def create(self, *, kind, topic, papers, model=None, filters=None, source=None, notice=None):
        record_id, now = uuid4().hex, timestamp()
        status = "queued" if kind == "review" else "completed"
        progress = "Waiting to generate the review…" if kind == "review" else "Search saved."
        with self.connect() as db:
            db.execute("""
                INSERT INTO history
                (id, kind, topic, model, papers, filters, source, notice, status, progress, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (record_id, kind, topic, model, json.dumps(papers),
                  json.dumps(filters) if filters is not None else None,
                  source, notice, status, progress, now, now))
        return record_id

    def get(self, record_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM history WHERE id = ?", (record_id,)).fetchone()
        if row is None:
            return None
        record = dict(row)
        for key in ("papers", "evidence", "filters"):
            record[key] = json.loads(record[key]) if record[key] is not None else None
        return record

    def list(self, limit=20, offset=0):
        with self.connect() as db:
            rows = db.execute("""
                SELECT id, kind, topic, model, status, progress, error, created_at, updated_at,
                       json_array_length(papers) AS paper_count
                FROM history ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?
            """, (limit + 1, offset)).fetchall()
        return {"items": [dict(row) for row in rows[:limit]], "has_more": len(rows) > limit}

    def progress(self, record_id, message):
        with self.connect() as db:
            db.execute("""
                UPDATE history SET status = 'running', progress = ?, updated_at = ?
                WHERE id = ? AND status IN ('queued', 'running')
            """, (message, timestamp(), record_id))

    def complete(self, record_id, review, evidence):
        with self.connect() as db:
            db.execute("""
                UPDATE history SET status = 'completed', progress = 'Review saved.',
                    review = ?, evidence = ?, updated_at = ?
                WHERE id = ? AND status IN ('queued', 'running')
            """, (review, json.dumps(evidence), timestamp(), record_id))

    def fail(self, record_id, message):
        with self.connect() as db:
            db.execute("""
                UPDATE history SET status = 'failed', progress = 'Review stopped.', error = ?, updated_at = ?
                WHERE id = ? AND status IN ('queued', 'running')
            """, (message, timestamp(), record_id))

    def recover_interrupted(self):
        with self.connect() as db:
            db.execute("""
                UPDATE history SET status = 'failed', progress = 'Review interrupted.',
                    error = 'The backend restarted before this review finished. Open its papers and generate again.',
                    updated_at = ? WHERE kind = 'review' AND status IN ('queued', 'running')
            """, (timestamp(),))

    def save_pdf(self, url, data):
        pdf_id = hashlib.sha256(url.encode()).hexdigest()
        with self.connect() as db:
            db.execute("INSERT OR IGNORE INTO pdfs (id, url, data, created_at) VALUES (?, ?, ?, ?)",
                       (pdf_id, url, data, timestamp()))
        return pdf_id

    def get_pdf(self, *, url=None, pdf_id=None):
        with self.connect() as db:
            if url is not None:
                row = db.execute("SELECT data FROM pdfs WHERE url = ?", (url,)).fetchone()
            else:
                row = db.execute("SELECT data FROM pdfs WHERE id = ?", (pdf_id,)).fetchone()
        return bytes(row["data"]) if row is not None else None

    def pdf_link(self, url):
        with self.connect() as db:
            row = db.execute("SELECT id FROM pdfs WHERE url = ?", (url,)).fetchone()
        return f"/api/pdfs/{row['id']}" if row else None
