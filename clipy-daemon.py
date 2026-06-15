#!/usr/bin/env python3
"""
Clipy Daemon — Lightweight background clipboard monitor.

Polls the system clipboard every 500ms via xsel, stores unique clips
in a local SQLite database, auto-purges expired entries, and enforces
a maximum history cap.  Runs as a systemd user service.
"""

import hashlib
import os
import re
import sys
import time
import sqlite3
import subprocess
import threading

# Force GDK to X11 to bypass Wayland background isolation
os.environ["GDK_BACKEND"] = "x11"

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
gi.require_version('GdkPixbuf', '2.0')
from gi.repository import Gtk, Gdk, GdkPixbuf, GLib

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "clipy.db")
IMAGES_DIR = os.path.expanduser("~/.config/clipy/images/")
POLL_INTERVAL = 500          # milliseconds between clipboard checks
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
    # Ensure images directory exists
    os.makedirs(IMAGES_DIR, exist_ok=True)
    
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
    c.execute('''
        CREATE TABLE IF NOT EXISTS snippets (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            label      TEXT,
            content    TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
# Clipboard & File Cleanup helpers
# ---------------------------------------------------------------------------

def delete_image_file_if_needed(content, content_type):
    if content_type == 'image' and content and os.path.exists(content):
        try:
            os.remove(content)
            print(f"[clipy] deleted image file: {content}")
        except Exception as exc:
            print(f"[clipy] failed to delete image file: {exc}", file=sys.stderr)


def save_text_clip(text, content_type):
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
        ''', (text, content_type))
        
        # Select unpinned items beyond limit to delete their image files on disk
        c.execute('''
            SELECT content, content_type FROM clipboard_history
            WHERE pinned = 0
            ORDER BY created_at DESC
            LIMIT -1 OFFSET ?
        ''', (MAX_HISTORY,))
        to_delete = c.fetchall()
        for content, ctype in to_delete:
            delete_image_file_if_needed(content, ctype)
            
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
        preview = text.strip()[:40].replace('\n', ' ')
        print(f"[clipy] saved ({content_type}): {preview}…")
    except Exception as exc:
        print(f"[clipy] db error saving text: {exc}", file=sys.stderr)


def save_image_clip(filepath, image_hash):
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        
        # Upsert
        c.execute('''
            INSERT INTO clipboard_history (content, created_at, pinned, content_type)
            VALUES (?, CURRENT_TIMESTAMP, 0, 'image')
            ON CONFLICT(content) DO UPDATE SET
                created_at = CURRENT_TIMESTAMP
        ''', (filepath,))
        
        # Select unpinned items beyond limit to delete their image files on disk
        c.execute('''
            SELECT content, content_type FROM clipboard_history
            WHERE pinned = 0
            ORDER BY created_at DESC
            LIMIT -1 OFFSET ?
        ''', (MAX_HISTORY,))
        to_delete = c.fetchall()
        for content, ctype in to_delete:
            delete_image_file_if_needed(content, ctype)
            
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
        print(f"[clipy] saved (image): {filepath} (hash: {image_hash})")
    except Exception as exc:
        print(f"[clipy] db error saving image: {exc}", file=sys.stderr)


def prune_expired_items():
    try:
        hours = get_retention_hours()
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        
        c.execute('''
            SELECT content, content_type FROM clipboard_history
            WHERE pinned = 0
              AND created_at < datetime('now', ?)
        ''', (f"-{hours} hours",))
        to_delete = c.fetchall()
        for content, ctype in to_delete:
            delete_image_file_if_needed(content, ctype)
            
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
    return True


# ---------------------------------------------------------------------------
# Daemon Polling Class
# ---------------------------------------------------------------------------

class ClipyDaemon:
    def __init__(self):
        Gtk.init()
        self.clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        self.last_text = ""
        self.last_image_hash = ""
        self._init_last_states()
        
    def _init_last_states(self):
        if self.clipboard.wait_is_image_available():
            pixbuf = self.clipboard.wait_for_image()
            if pixbuf:
                try:
                    self.last_image_hash = hashlib.md5(pixbuf.get_pixels()).hexdigest()
                except Exception:
                    pass
        elif self.clipboard.wait_is_text_available():
            text = self.clipboard.wait_for_text()
            if text:
                self.last_text = text

    def poll_clipboard(self):
        # 1. Check for image first
        if self.clipboard.wait_is_image_available():
            pixbuf = self.clipboard.wait_for_image()
            if pixbuf:
                try:
                    pixels = pixbuf.get_pixels()
                    h = hashlib.md5(pixels).hexdigest()
                    if h != self.last_image_hash:
                        self.last_image_hash = h
                        self.last_text = ""  # Reset text cache so copy-back works
                        os.makedirs(IMAGES_DIR, exist_ok=True)
                        filepath = os.path.join(IMAGES_DIR, f"{h}.png")
                        pixbuf.savev(filepath, "png", [], [])
                        save_image_clip(filepath, h)
                except Exception as exc:
                    print(f"[clipy] error processing image clip: {exc}", file=sys.stderr)
                
        # 2. Check for text
        elif self.clipboard.wait_is_text_available():
            text = self.clipboard.wait_for_text()
            if text and text.strip() and text != self.last_text:
                if is_sensitive(text):
                    self.last_text = text
                    print("[clipy] skipped sensitive content", file=sys.stderr)
                else:
                    self.last_text = text
                    self.last_image_hash = ""  # Reset image cache so copy-back works
                    content_type = classify_content(text)
                    save_text_clip(text, content_type)
                
        return True


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main():
    init_db()
    daemon = ClipyDaemon()
    
    print(f"[clipy] daemon started — polling every {POLL_INTERVAL}ms, "
          f"retention {get_retention_hours()}h, max {MAX_HISTORY} items")

    # Set up GLib timeouts
    GLib.timeout_add(POLL_INTERVAL, daemon.poll_clipboard)
    GLib.timeout_add_seconds(PRUNE_INTERVAL, prune_expired_items)

    try:
        Gtk.main()
    except KeyboardInterrupt:
        pass

    print("[clipy] daemon stopped")


if __name__ == '__main__':
    main()
