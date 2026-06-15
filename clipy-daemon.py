#!/usr/bin/env python3
"""
Clipy Daemon — Lightweight background clipboard monitor.

Polls the system clipboard every 500ms via xsel, stores unique clips
in a local SQLite database, auto-purges expired entries, and enforces
a maximum history cap.  Runs as a systemd user service.
"""

import os
import re
import sys
import time
import sqlite3
import subprocess
import threading

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "clipy.db")
POLL_INTERVAL = 0.5          # seconds between clipboard checks
PRUNE_INTERVAL = 60          # seconds between prune sweeps
DEFAULT_RETENTION_HOURS = 4
MAX_HISTORY = 50

# ---------------------------------------------------------------------------
# Sensitive-data patterns (never stored)
# ---------------------------------------------------------------------------
SENSITIVE_PATTERNS = [
    # Credit / debit card numbers (13-19 digits, optional separators)
    re.compile(r'\b(?:\d[ -]*?){13,19}\b'),
    # Common API tokens / secrets
    re.compile(r'\b(?:sk-|sk_live_|sk_test_|ghp_|gho_|github_pat_|glpat-|xoxb-|xoxp-|AKIA[0-9A-Z]{16})\S+', re.I),
    # Bearer tokens
    re.compile(r'Bearer\s+[A-Za-z0-9\-._~+/]+=*', re.I),
    # password= or passwd= in config lines
    re.compile(r'(?:password|passwd|secret|token)\s*[:=]\s*\S+', re.I),
]

# ---------------------------------------------------------------------------
# Content-type classifier
# ---------------------------------------------------------------------------
URL_RE   = re.compile(r'^https?://', re.I)
EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', re.I)
CODE_HINTS = re.compile(r'(?:def |function |import |#include|class |const |let |var |=>|\{.*\})', re.S)
NUM_RE   = re.compile(r'^[\d\s\-+().]+$')


def classify_content(text: str) -> str:
    stripped = text.strip()
    if URL_RE.match(stripped):
        return "url"
    if EMAIL_RE.match(stripped):
        return "email"
    if NUM_RE.match(stripped) and len(stripped) <= 30:
        return "number"
    if CODE_HINTS.search(stripped):
        return "code"
    return "text"


def is_sensitive(text: str) -> bool:
    for pat in SENSITIVE_PATTERNS:
        if pat.search(text):
            return True
    return False

# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS clipboard_history (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            content      TEXT UNIQUE,
            created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            pinned       INTEGER DEFAULT 0,
            content_type TEXT DEFAULT 'text'
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT
        )
    ''')
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('retention_hours', ?)",
              (str(DEFAULT_RETENTION_HOURS),))
    conn.commit()
    conn.close()


def get_retention_hours() -> int:
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT value FROM settings WHERE key = 'retention_hours'")
        row = c.fetchone()
        conn.close()
        return int(row[0]) if row else DEFAULT_RETENTION_HOURS
    except Exception:
        return DEFAULT_RETENTION_HOURS

# ---------------------------------------------------------------------------
# Clipboard interaction via xsel
# ---------------------------------------------------------------------------

def read_clipboard() -> str | None:
    try:
        res = subprocess.run(
            ['xsel', '-b', '-o'],
            capture_output=True, text=True, timeout=1.0, errors='replace',
        )
        if res.returncode == 0:
            return res.stdout
    except Exception as exc:
        print(f"[clipy] clipboard read error: {exc}", file=sys.stderr)
    return None

# ---------------------------------------------------------------------------
# Background threads
# ---------------------------------------------------------------------------

def clipboard_poller():
    """Poll the clipboard and store new, non-sensitive content."""
    last_value = read_clipboard() or ""

    while True:
        time.sleep(POLL_INTERVAL)
        current = read_clipboard()
        if current is None or not current.strip():
            continue
        if current == last_value:
            continue

        last_value = current

        # Skip sensitive data
        if is_sensitive(current):
            print("[clipy] skipped sensitive content", file=sys.stderr)
            continue

        content_type = classify_content(current)

        try:
            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()

            # Upsert: bump timestamp if duplicate, otherwise insert
            c.execute('''
                INSERT INTO clipboard_history (content, created_at, pinned, content_type)
                VALUES (?, CURRENT_TIMESTAMP, 0, ?)
                ON CONFLICT(content) DO UPDATE SET
                    created_at   = CURRENT_TIMESTAMP,
                    content_type = excluded.content_type
            ''', (current, content_type))

            # Enforce max history cap — remove oldest unpinned beyond limit
            c.execute('''
                DELETE FROM clipboard_history
                WHERE id IN (
                    SELECT id FROM clipboard_history
                    WHERE pinned = 0
                    ORDER BY created_at DESC
                    LIMIT -1 OFFSET ?
                )
            ''', (MAX_HISTORY,))

            conn.commit()
            conn.close()

            preview = current.strip()[:40].replace('\n', ' ')
            print(f"[clipy] saved ({content_type}): {preview}…")
        except Exception as exc:
            print(f"[clipy] db error: {exc}", file=sys.stderr)


def pruner():
    """Periodically remove expired, unpinned entries."""
    while True:
        time.sleep(PRUNE_INTERVAL)
        try:
            hours = get_retention_hours()
            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()
            c.execute('''
                DELETE FROM clipboard_history
                WHERE pinned = 0
                  AND created_at < datetime('now', ?)
            ''', (f"-{hours} hours",))
            deleted = c.rowcount
            conn.commit()
            conn.close()
            if deleted:
                print(f"[clipy] pruned {deleted} expired item(s)")
        except Exception as exc:
            print(f"[clipy] prune error: {exc}", file=sys.stderr)

# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main():
    init_db()
    print(f"[clipy] daemon started — polling every {POLL_INTERVAL}s, "
          f"retention {get_retention_hours()}h, max {MAX_HISTORY} items")

    threading.Thread(target=clipboard_poller, daemon=True).start()
    threading.Thread(target=pruner, daemon=True).start()

    # Keep main thread alive
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass

    print("[clipy] daemon stopped")


if __name__ == '__main__':
    main()
