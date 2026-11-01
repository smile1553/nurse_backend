"""Durable upload outbox. Local results remain authoritative if the website is offline."""
from contextlib import contextmanager
import asyncio
import hashlib
import json
import os
import sqlite3
import time
from pathlib import Path
from urllib.parse import urlparse

class ResultUploader:
    def __init__(self, result_dir, url=None, api_key=None, send=None):
        self.result_dir = Path(result_dir)
        self.db_path = self.result_dir / "upload_outbox.sqlite3"
        self.url = (url if url is not None else os.getenv("RESULT_UPLOAD_URL", "")).strip()
        self.api_key = api_key if api_key is not None else os.getenv("RESULT_UPLOAD_API_KEY", "")
        self._send = send
        self._task = None
        self._stop = None
        self.include_existing = os.getenv("RESULT_UPLOAD_INCLUDE_EXISTING", "0").strip().lower() in {"1", "true", "yes", "on"}
        # Persist the discovery boundary before new reports can be saved. Existing
        # classroom data is not uploaded unless the administrator opts in.
        self.discovery_since = time.time()
        try:
            with self._connect() as db:
                self.discovery_since = float(db.execute(
                    "SELECT value FROM upload_settings WHERE name='discovery_since'"
                ).fetchone()[0])
        except (OSError, sqlite3.Error):
            print("[upload] outbox unavailable; local backend can still start")

    @property
    def enabled(self):
        return bool(self.url and self.api_key)

    @contextmanager
    def _connect(self):
        self.result_dir.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.db_path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("""CREATE TABLE IF NOT EXISTS uploads (
            source_key TEXT PRIMARY KEY, payload TEXT NOT NULL, digest TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
            next_attempt REAL NOT NULL DEFAULT 0, last_error TEXT,
            uploaded_at REAL)""")
        db.execute("CREATE TABLE IF NOT EXISTS upload_settings (name TEXT PRIMARY KEY, value TEXT NOT NULL)")
        db.execute("INSERT OR IGNORE INTO upload_settings VALUES ('discovery_since', ?)", (str(self.discovery_since),))
        try:
            with db:
                yield db
        finally:
            db.close()

    def enqueue_file(self, path):
        record = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        if not all(record.get(k) for k in ("studentId", "sessionId", "resultId", "loginTime")):
            return False
        if not all(k in record for k in ("correctCount", "questionScore", "toneScore", "totalScore")):
            return False
        payload = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(payload.encode()).hexdigest()
        key = record["sessionId"] + "/" + record["resultId"]
        with self._connect() as db:
            db.execute("""INSERT INTO uploads(source_key,payload,digest) VALUES(?,?,?)
                ON CONFLICT(source_key) DO NOTHING""", (key,payload,digest))
        # Freeze the first saved snapshot. Unity retries may regenerate reports;
        # the teacher API rejects changed content for an existing source key.
        return True

    def discover(self):
        # Recover a crash between saving the report JSON and enqueueing it.
        for path in self.result_dir.glob("????-??-??/*.json"):
            try:
                if not self.include_existing and path.stat().st_mtime < self.discovery_since:
                    continue
                self.enqueue_file(path)
            except (OSError, ValueError, TypeError):
                print("[upload] could not read a result JSON; will retry discovery")

    def _post(self, payload):
        if self._send:
            return self._send(payload)
        import httpx
        parsed = urlparse(self.url)
        if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost"}):
            raise ValueError("RESULT_UPLOAD_URL must use HTTPS")
        # Do not follow redirects with the upload credential.
        with httpx.Client(timeout=15, follow_redirects=False) as client:
            return client.post(self.url, content=payload.encode("utf-8"),
                headers={"Authorization": "Bearer " + self.api_key, "Content-Type": "application/json"})

    def tick(self):
        if not self.enabled:
            return
        with self._connect() as db:
            pending = db.execute("SELECT * FROM uploads WHERE state='pending' AND next_attempt<=? ORDER BY next_attempt LIMIT 10", (time.time(),)).fetchall()
        for row in pending:
            try:
                response = self._post(row["payload"])
                if 200 <= response.status_code < 300:
                    body = response.json()
                    if body.get("ok") is not True:
                        raise ValueError("Website did not acknowledge result")
                    with self._connect() as db:
                        db.execute("UPDATE uploads SET state='uploaded',uploaded_at=?,last_error=NULL WHERE source_key=? AND digest=?",
                                   (time.time(), row["source_key"], row["digest"]))
                    print("[upload] result uploaded")
                    continue
                permanent = response.status_code in {400, 409, 413, 422}
                # Store status only; response bodies might contain sensitive configuration.
                error = "HTTP " + str(response.status_code)
            except Exception:
                permanent, error = False, "network or response failure"
            attempts = row["attempts"] + 1
            delay = min(3600, 5 * 2 ** min(attempts, 10))
            with self._connect() as db:
                db.execute("UPDATE uploads SET state=?,attempts=?,next_attempt=?,last_error=? WHERE source_key=? AND digest=?",
                    ("blocked" if permanent else "pending", attempts, time.time()+delay, error, row["source_key"], row["digest"]))
            print("[upload] " + error + ("; needs review" if permanent else "; will retry"))

    def status(self):
        with self._connect() as db:
            counts = {row["state"]: row["n"] for row in db.execute("SELECT state,count(*) n FROM uploads GROUP BY state")}
            issues = [dict(row) for row in db.execute("SELECT source_key,state,attempts,last_error FROM uploads WHERE state<>'uploaded' ORDER BY next_attempt LIMIT 30")]
        return {"enabled": self.enabled, "counts": counts, "issues": issues}

    async def _run(self):
        cycles = 0
        while not self._stop.is_set():
            try:
                if cycles % 6 == 0:
                    await asyncio.to_thread(self.discover)
                await asyncio.to_thread(self.tick)
            except Exception:
                print("[upload] outbox unavailable; will retry")
            cycles += 1
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=5)
            except asyncio.TimeoutError:
                pass

    async def start(self):
        if not self.enabled:
            print("[upload] disabled: configure RESULT_UPLOAD_URL and RESULT_UPLOAD_API_KEY")
            return
        if self._task is None:
            self._stop = asyncio.Event()
            self._task = asyncio.create_task(self._run())

    async def stop(self):
        if self._task:
            self._stop.set()
            await self._task
            self._task = None

