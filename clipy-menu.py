#!/usr/bin/env python3
"""
Clipy Menu — Native GTK 3 clipboard history popup.

Opens a borderless, floating, glassmorphic popup window styled with
GTK CSS.  Each clipboard entry is rendered as a card with content
preview, type badge, age label, pin state, and expiry bar.

Keyboard-driven:
    ↑/↓    navigate cards
    Enter  copy → paste into previous window → close
    P      pin / unpin
    Delete remove card
    /      focus search
    Esc    close
"""

import json
import os
import re
import sys
import shutil
import sqlite3
import subprocess
import time
from urllib.parse import urlparse

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
from gi.repository import Gtk, Gdk, GLib, Pango, GdkPixbuf

# ---------------------------------------------------------------------------
# Paths & config
# ---------------------------------------------------------------------------
DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "clipy.db")
MAX_HISTORY = 50
HAS_XDOTOOL = shutil.which("xdotool") is not None
PREVIOUS_WINDOW_ID = None

# Capture the previously-active window *before* we open the popup
if HAS_XDOTOOL:
    try:
        res = subprocess.run(['xdotool', 'getactivewindow'],
                             capture_output=True, text=True, timeout=1)
        if res.returncode == 0:
            PREVIOUS_WINDOW_ID = res.stdout.strip()
    except Exception:
        pass

# ---------------------------------------------------------------------------
# Type badge map
# ---------------------------------------------------------------------------
TYPE_BADGES = {
    "url":    "URL",
    "email":  "EMAIL",
    "code":   "CODE",
    "number": "NUMBER",
    "text":   "TEXT",
    "image":  "IMAGE",
}

# ---------------------------------------------------------------------------
# Color detection for hex color preview
# ---------------------------------------------------------------------------
HEX_WITH_HASH = re.compile(r'#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b')
HEX_WITHOUT_HASH_6 = re.compile(r'^[0-9a-fA-F]{6}$')
HEX_WITHOUT_HASH_3 = re.compile(r'^[0-9a-fA-F]{3}$')

def detect_hex_color(text):
    """Return the hex color found in text (with leading '#'), or None."""
    stripped = text.strip()
    
    # 1. Try matching with hash first (e.g., #7c5cdb)
    m = HEX_WITH_HASH.search(stripped)
    if m:
        return m.group(0)
    
    # 2. Try matching if the entire string is just a 6-digit hex color (e.g., F7E49B)
    if HEX_WITHOUT_HASH_6.match(stripped):
        return "#" + stripped
        
    # 3. Try matching if the entire string is a 3-digit hex color containing at least one digit (e.g., 333)
    if HEX_WITHOUT_HASH_3.match(stripped) and any(c.isdigit() for c in stripped):
        return "#" + stripped
        
    return None


# ---------------------------------------------------------------------------
# GTK CSS — glassmorphic / Fluent dark theme
# ---------------------------------------------------------------------------
CSS = b"""
/* ---- window ---- */
window {
    background-color: #000000;
}
.titlebar-label {
    color: #8a8a8a;
    font-size: 11px;
    font-weight: 600;
    font-family: 'Outfit', 'Cantarell', sans-serif;
}
.traffic-light {
    min-width: 13px;
    min-height: 13px;
    border-radius: 999px;
    border: 1px solid;
    padding: 0;
    box-shadow: inset 0 -1px 1px rgba(0, 0, 0, 0.2);
}
.traffic-light label {
    color: #ffffff;
    font-family: 'Outfit', 'Cantarell', sans-serif;
    font-size: 9px;
    font-weight: 800;
    padding: 0;
}
.traffic-close {
    background-color: #ff5f57;
    border-color: rgba(0, 0, 0, 0.35);
}
.traffic-close:hover {
    background-color: #ff867d;
}
.traffic-minimize {
    background-color: #febc2e;
}
.traffic-minimize:hover {
    background-color: #ffd565;
}
.traffic-maximize {
    background-color: #28c840;
}
.traffic-maximize:hover {
    background-color: #5ede74;
}

/* ---- search entry ---- */
entry {
    background-color: rgba(255, 255, 255, 0.04);
    border: 1px solid rgba(255, 255, 255, 0.14);
    border-radius: 10px;
    color: #ffffff;
    padding: 10px 14px;
    font-family: 'Outfit', 'Cantarell', sans-serif;
    font-size: 14px;
    caret-color: #ffffff;
    min-height: 20px;
}
entry:focus {
    border-color: rgba(255, 255, 255, 0.80);
    box-shadow: 0 0 0 1px rgba(255, 255, 255, 0.25),
                0 0 12px rgba(255, 255, 255, 0.12);
}

/* ---- card (each history item) ---- */
.clip-card {
    background-color: #121212;
    border: 1px solid #262626;
    border-radius: 10px;
    padding: 12px 14px;
}
.clip-card:hover {
    background-color: #1a1a1a;
    border-color: #3a3a3a;
}
.clip-card.focused {
    background-color: #1f1f1f;
    border-color: #ffffff;
    box-shadow: 0 0 0 1px rgba(255, 255, 255, 0.35),
                0 4px 18px rgba(0, 0, 0, 0.55),
                0 0 14px rgba(255, 255, 255, 0.10);
}
.clip-card.selected {
    background-color: #1a1a1a;
    border-color: #ffffff;
    box-shadow: 0 0 0 1px rgba(255, 255, 255, 0.40),
                0 0 10px rgba(255, 255, 255, 0.10);
}

/* ---- text inside cards ---- */
.clip-content {
    color: #e5e5e5;
    font-family: 'Outfit', 'Cantarell', sans-serif;
    font-size: 13px;
}
.clip-meta {
    color: #8a8a8a;
    font-size: 11px;
}
.clip-domain {
    color: #a3a3a3;
    font-size: 10px;
    font-family: 'Outfit', 'Cantarell', sans-serif;
    padding: 1px 2px;
}

/* ---- type badges (monochrome) ---- */
.clip-badge {
    font-size: 10px;
    font-weight: 500;
    font-family: 'Outfit', 'Cantarell', sans-serif;
    padding: 2px 8px;
    border-radius: 4px;
    background-color: rgba(255, 255, 255, 0.05);
    border: 1px solid rgba(255, 255, 255, 0.14);
    color: #bdbdbd;
    letter-spacing: 0.3px;
}
.clip-badge-pinned {
    color: #ffffff;
    border-color: rgba(255, 255, 255, 0.45);
    background-color: rgba(255, 255, 255, 0.10);
    font-weight: 700;
}

/* ---- header / title ---- */
.header-title {
    color: #ffffff;
    font-size: 17px;
    font-weight: 700;
    font-family: 'Outfit', 'Cantarell', sans-serif;
}
.header-subtitle {
    color: #8a8a8a;
    font-size: 11px;
    font-family: 'Outfit', 'Cantarell', sans-serif;
}
.header-count {
    color: #bdbdbd;
    font-size: 12px;
    padding: 3px 10px;
    border-radius: 6px;
    background-color: rgba(255, 255, 255, 0.05);
    border: 1px solid #2a2a2a;
}

/* ---- expiry progress bar ---- */
progressbar {
    border: 0;
    outline: 0;
    background-color: transparent;
}
progressbar trough {
    background-color: rgba(255, 255, 255, 0.06);
    border: 1px solid rgba(255, 255, 255, 0.25);
    border-radius: 3px;
    min-height: 4px;
}
progressbar progress {
    border: 0;
    border-radius: 2px;
    min-height: 2px;
    background-color: #ffffff;
}
progressbar.warning progress,
progressbar.danger progress {
    background-color: #9b9b9b;
}

/* ---- scrollbar ---- */
scrolledwindow scrollbar {
    background-color: transparent;
}
scrolledwindow scrollbar slider {
    background-color: rgba(255, 255, 255, 0.18);
    border-radius: 10px;
    min-width: 6px;
}
scrolledwindow scrollbar slider:hover {
    background-color: rgba(255, 255, 255, 0.32);
}

/* ---- footer ---- */
.footer-label {
    color: #6b6b6b;
    font-size: 10px;
    font-family: 'Outfit', 'Cantarell', sans-serif;
}

/* ---- empty state ---- */
.empty-label {
    color: #6b6b6b;
    font-size: 14px;
    font-family: 'Outfit', 'Cantarell', sans-serif;
}

/* ---- color swatch ---- */
.color-swatch {
    border-radius: 3px;
    min-width: 18px;
    min-height: 18px;
    border: 1px solid rgba(255, 255, 255, 0.30);
    box-shadow: 0 2px 6px rgba(0, 0, 0, 0.45);
}

/* ---- stats bar ---- */
.stats-bar {
    color: #6b6b6b;
    font-size: 10px;
    font-family: 'Outfit', 'Cantarell', sans-serif;
    padding: 4px 0;
}
.stats-bar-highlight {
    color: #ffffff;
    font-size: 10px;
    font-weight: 600;
}

/* ---- mode indicator ---- */
.mode-label {
    color: #ffffff;
    font-size: 11px;
    font-weight: 700;
    font-family: 'Outfit', 'Cantarell', sans-serif;
}

/* ---- filter tabs ---- */
.filter-btn {
    background-color: transparent;
    border: 1px solid transparent;
    color: #8a8a8a;
    font-size: 11px;
    font-family: 'Outfit', 'Cantarell', sans-serif;
    padding: 4px 10px;
    border-radius: 6px;
}
.filter-btn:hover {
    background-color: rgba(255, 255, 255, 0.06);
    color: #e5e5e5;
    border-color: rgba(255, 255, 255, 0.25);
}
.filter-btn.active-filter {
    background-color: rgba(255, 255, 255, 0.10);
    border-color: #ffffff;
    color: #ffffff;
    font-weight: 700;
    box-shadow: 0 0 0 1px rgba(255, 255, 255, 0.20);
}

/* ---- card action bar & buttons ---- */
.card-action-bar {
    margin-top: 4px;
    padding-top: 4px;
    border-top: 1px dashed rgba(255, 255, 255, 0.08);
}
.card-action-btn {
    background-color: rgba(255, 255, 255, 0.04);
    border: 1px solid rgba(255, 255, 255, 0.10);
    border-radius: 4px;
    color: #a0a0a0;
    font-family: 'Outfit', 'Cantarell', sans-serif;
    font-size: 10px;
    padding: 2px 7px;
}
.card-action-btn:hover {
    background-color: rgba(255, 255, 255, 0.15);
    border-color: rgba(255, 255, 255, 0.35);
    color: #ffffff;
}
.card-action-btn.active-action {
    background-color: rgba(255, 255, 255, 0.20);
    border-color: #ffffff;
    color: #ffffff;
    font-weight: 700;
}
.card-action-btn.danger-action:hover {
    background-color: rgba(255, 85, 85, 0.25);
    border-color: #ff5555;
    color: #ff8888;
}
"""

# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def get_retention_hours() -> int:
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT value FROM settings WHERE key = 'retention_hours'")
        row = c.fetchone()
        conn.close()
        return int(row[0]) if row else 4
    except Exception:
        return 4


def fetch_history():
    """Return list of dicts sorted newest-first."""
    if not os.path.exists(DB_FILE):
        return []
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute('''
            SELECT id, content, created_at, pinned, content_type,
                   (strftime('%s','now') - strftime('%s', created_at)) AS age_s
            FROM clipboard_history
            ORDER BY pinned DESC, created_at DESC
        ''')
        rows = c.fetchall()
        conn.close()

        retention_s = get_retention_hours() * 3600
        items = []
        for r in rows:
            items.append({
                "id":          r[0],
                "content":     r[1],
                "created_at":  r[2],
                "pinned":      bool(r[3]),
                "type":        r[4] or "text",
                "age_s":       r[5],
                "expires_in":  max(0, retention_s - r[5]) if not r[3] else None,
                "retention_s": retention_s,
            })
        return items
    except Exception as exc:
        print(f"[clipy-menu] db error: {exc}", file=sys.stderr)
        return []


def delete_item(item_id):
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT content, content_type FROM clipboard_history WHERE id = ?", (item_id,))
        row = c.fetchone()
        if row:
            content, ctype = row[0], row[1]
            if ctype == 'image' and content and os.path.exists(content):
                try:
                    os.remove(content)
                except Exception as e:
                    print(f"[clipy-menu] error deleting image: {e}", file=sys.stderr)
        c.execute("DELETE FROM clipboard_history WHERE id = ?", (item_id,))
        conn.commit()
        conn.close()
    except Exception as exc:
        print(f"[clipy-menu] db delete error: {exc}", file=sys.stderr)


def toggle_pin(item_id, currently_pinned):
    conn = sqlite3.connect(DB_FILE)
    conn.execute("UPDATE clipboard_history SET pinned = ? WHERE id = ?",
                 (0 if currently_pinned else 1, item_id))
    conn.commit()
    conn.close()


def copy_to_clipboard(item):
    try:
        clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        if item.get("type") == "image":
            if os.path.exists(item["content"]):
                pixbuf = GdkPixbuf.Pixbuf.new_from_file(item["content"])
                clipboard.set_image(pixbuf)
                clipboard.store()
                while Gtk.events_pending():
                    Gtk.main_iteration()
        else:
            clipboard.set_text(item["content"], -1)
            clipboard.store()
            while Gtk.events_pending():
                Gtk.main_iteration()
    except Exception as exc:
        print(f"[clipy-menu] copy error: {exc}", file=sys.stderr)


def paste_to_previous_window():
    """Refocus the window that was active before Clipy and simulate Ctrl+V."""
    if not HAS_XDOTOOL or not PREVIOUS_WINDOW_ID:
        return
    try:
        subprocess.run(['xdotool', 'windowactivate', '--sync', PREVIOUS_WINDOW_ID],
                       timeout=2)
        time.sleep(0.05)
        subprocess.run(['xdotool', 'key', '--clearmodifiers', 'ctrl+v'],
                       timeout=2)
    except Exception as exc:
        print(f"[clipy-menu] paste error: {exc}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Snippet helpers
# ---------------------------------------------------------------------------

def save_snippet(label, content):
    conn = sqlite3.connect(DB_FILE)
    conn.execute("INSERT INTO snippets (label, content) VALUES (?, ?)", (label, content))
    conn.commit()
    conn.close()


def fetch_snippets():
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT id, label, content, created_at FROM snippets ORDER BY created_at DESC")
        rows = c.fetchall()
        conn.close()
        return [{"id": r[0], "label": r[1], "content": r[2], "created_at": r[3],
                 "pinned": True, "type": "snippet", "age_s": 0,
                 "expires_in": None, "retention_s": 0} for r in rows]
    except Exception:
        return []


def delete_snippet(snippet_id):
    conn = sqlite3.connect(DB_FILE)
    conn.execute("DELETE FROM snippets WHERE id = ?", (snippet_id,))
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Stats helper
# ---------------------------------------------------------------------------

def get_clipboard_stats():
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM clipboard_history")
        total = c.fetchone()[0]
        c.execute("""SELECT COUNT(*) FROM clipboard_history
                     WHERE created_at >= datetime('now', '-1 day')""")
        today = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM clipboard_history WHERE content_type = 'image'")
        images = c.fetchone()[0]
        c.execute("""SELECT MIN(strftime('%s','now') - strftime('%s', created_at))
                     FROM clipboard_history""")
        row = c.fetchone()
        oldest_age = row[0] if row and row[0] is not None else None
        c.execute("SELECT COUNT(*) FROM snippets")
        snippets = c.fetchone()[0]
        conn.close()
        try:
            db_size = os.path.getsize(DB_FILE)
        except OSError:
            db_size = 0
        return {"total": total, "today": today, "images": images,
                "snippets": snippets, "oldest_age": oldest_age,
                "db_size": db_size}
    except Exception:
        return {"total": 0, "today": 0, "images": 0, "snippets": 0,
                "oldest_age": None, "db_size": 0}

# ---------------------------------------------------------------------------
# Helpers
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


def save_text_clip(text, content_type):
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute('''
            INSERT INTO clipboard_history (content, created_at, pinned, content_type)
            VALUES (?, CURRENT_TIMESTAMP, 0, ?)
            ON CONFLICT(content) DO UPDATE SET
                created_at   = CURRENT_TIMESTAMP,
                content_type = excluded.content_type
        ''', (text, content_type))
        
        c.execute('''
            SELECT content, content_type FROM clipboard_history
            WHERE pinned = 0
            ORDER BY created_at DESC
            LIMIT -1 OFFSET ?
        ''', (MAX_HISTORY,))
        to_delete = c.fetchall()
        for content, ctype in to_delete:
            if ctype == 'image' and content and os.path.exists(content):
                try:
                    os.remove(content)
                except Exception as e:
                    print(f"[clipy-menu] error deleting image: {e}", file=sys.stderr)
            
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
    except Exception as exc:
        print(f"[clipy-menu] db error saving text: {exc}", file=sys.stderr)


def format_age(seconds):
    if seconds < 60:
        return "Just now"
    mins = seconds // 60
    if mins < 60:
        return f"{mins}m ago"
    hours = mins // 60
    if hours < 24:
        return f"{hours}h ago"
    return f"{hours // 24}d ago"


def truncate(text, max_lines=3, max_chars=200):
    lines = text.splitlines()[:max_lines]
    result = "\n".join(lines)
    if len(result) > max_chars:
        result = result[:max_chars] + "…"
    elif len(text.splitlines()) > max_lines:
        result += " …"
    return result

# ---------------------------------------------------------------------------
# Main GTK Window
# ---------------------------------------------------------------------------

class ClipyWindow(Gtk.Window):
    def __init__(self):
        super().__init__(title="Clipy")
        self.set_default_size(460, 560)
        self.set_decorated(False)
        self.set_resizable(True)
        self.set_size_request(440, 500)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.set_type_hint(Gdk.WindowTypeHint.DIALOG)
        self.set_keep_above(True)

        # Set custom window icon
        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "clipy_icon.png")
        if os.path.exists(icon_path):
            try:
                self.set_icon_from_file(icon_path)
            except Exception:
                pass

        # Solid opaque background — no true transparency
        # (glassmorphic effect is achieved via card styling against the dark bg)

        # Close on focus-out
        self.connect("focus-out-event", self._on_focus_out)
        self.connect("key-press-event", self._on_key_press)

        # State
        self.all_items = []
        self.filtered_items = []
        self.focused_idx = -1
        self.card_widgets = []
        self.merge_mode = False
        self.selected_indices = set()
        self.current_view = "history"  # "history" or "snippets"
        self.pasted = False
        self._dialog_open = False

        # Layout
        self._build_ui()
        self._load_items()

    # ---- UI construction ----

    def _build_ui(self):
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        root.set_margin_top(10)
        root.set_margin_bottom(16)
        root.set_margin_start(20)
        root.set_margin_end(20)
        self.add(root)

        # Mac-style titlebar: traffic lights + draggable area
        titlebar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        titlebar.set_margin_bottom(10)

        self.btn_close = self._make_traffic_light("close", "#ff5f57", "#e0443e", "✕")
        self.btn_close.connect("clicked", self._on_titlebar_close)
        self.btn_minimize = self._make_traffic_light("minimize", "#febc2e", "#d99a1b", "−")
        self.btn_minimize.connect("clicked", self._on_titlebar_minimize)
        self.btn_maximize = self._make_traffic_light("maximize", "#28c840", "#1fa839", "+")
        self.btn_maximize.connect("clicked", self._on_titlebar_maximize)

        titlebar.pack_start(self.btn_close, False, False, 0)
        titlebar.pack_start(self.btn_minimize, False, False, 0)
        titlebar.pack_start(self.btn_maximize, False, False, 0)

        titlebar_label = Gtk.Label(label="Clipy")
        titlebar_label.get_style_context().add_class("titlebar-label")
        titlebar.pack_start(titlebar_label, True, True, 0)

        # Window titlebar drag (macOS-style toolbar dragging)
        titlebar.connect("button-press-event", self._on_titlebar_press)

        root.pack_start(titlebar, False, False, 0)

        # Header
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        header.set_margin_bottom(6)

        # Header Logo + Title row
        logo_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        
        # Load and scale custom icon
        icon_image = Gtk.Image()
        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "clipy_icon.png")
        if os.path.exists(icon_path):
            try:
                pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(icon_path, 32, 32, True)
                icon_image.set_from_pixbuf(pixbuf)
            except Exception:
                pass
        logo_row.pack_start(icon_image, False, False, 0)

        logo_text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        title = Gtk.Label(label="Clipy")
        title.set_halign(Gtk.Align.START)
        title.get_style_context().add_class("header-title")
        logo_text_box.pack_start(title, False, False, 0)

        subtitle = Gtk.Label(label="Clipboard History")
        subtitle.set_halign(Gtk.Align.START)
        subtitle.get_style_context().add_class("header-subtitle")
        logo_text_box.pack_start(subtitle, False, False, 2)

        logo_row.pack_start(logo_text_box, True, True, 0)
        header.pack_start(logo_row, True, True, 0)

        self.count_label = Gtk.Label(label="0 items")
        self.count_label.get_style_context().add_class("header-count")
        self.count_label.set_valign(Gtk.Align.CENTER)
        header.pack_end(self.count_label, False, False, 0)

        root.pack_start(header, False, False, 0)

        # Stats bar
        self.stats_label = Gtk.Label(label="")
        self.stats_label.set_halign(Gtk.Align.START)
        self.stats_label.get_style_context().add_class("stats-bar")
        self.stats_label.set_margin_bottom(8)
        root.pack_start(self.stats_label, False, False, 0)
        self._refresh_stats()

        # Filter tabs (History | Snippets) + mode indicator
        filter_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        filter_row.set_margin_bottom(10)

        self.btn_history = Gtk.Button(label="History")
        self.btn_history.get_style_context().add_class("filter-btn")
        self.btn_history.get_style_context().add_class("active-filter")
        self.btn_history.set_can_focus(False)
        self.btn_history.connect("clicked", lambda _: self._switch_view("history"))
        filter_row.pack_start(self.btn_history, False, False, 0)

        self.btn_snippets = Gtk.Button(label="Snippets")
        self.btn_snippets.get_style_context().add_class("filter-btn")
        self.btn_snippets.set_can_focus(False)
        self.btn_snippets.connect("clicked", lambda _: self._switch_view("snippets"))
        filter_row.pack_start(self.btn_snippets, False, False, 0)

        self.mode_label = Gtk.Label(label="")
        self.mode_label.get_style_context().add_class("mode-label")
        self.mode_label.set_halign(Gtk.Align.END)
        filter_row.pack_end(self.mode_label, False, False, 0)

        self.btn_merge_now = Gtk.Button(label="⚡ Merge Now")
        self.btn_merge_now.get_style_context().add_class("filter-btn")
        self.btn_merge_now.get_style_context().add_class("active-filter")
        self.btn_merge_now.set_can_focus(False)
        self.btn_merge_now.set_no_show_all(True)
        self.btn_merge_now.set_visible(False)
        self.btn_merge_now.connect("clicked", lambda _: self._execute_merge())
        filter_row.pack_end(self.btn_merge_now, False, False, 0)

        root.pack_start(filter_row, False, False, 0)

        # Type filter chips (All | URL | Email | Code | Number | Image)
        self.type_filter = None  # None = all types
        self.type_order = [None, "url", "email", "code", "number", "image"]
        self.type_buttons = {}
        type_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        type_row.set_margin_bottom(10)
        for label_text, t in [("All", None), ("URL", "url"), ("EMAIL", "email"),
                              ("CODE", "code"), ("NUMBER", "number"), ("IMAGE", "image")]:
            btn = Gtk.Button(label=label_text)
            btn.get_style_context().add_class("filter-btn")
            btn.set_can_focus(False)
            btn.connect("clicked", lambda _, t=t: self._set_type_filter(t))
            type_row.pack_start(btn, False, False, 0)
            self.type_buttons[t] = btn
        self.type_buttons[None].get_style_context().add_class("active-filter")
        root.pack_start(type_row, False, False, 0)

        # Search entry with clear icon
        self.search_entry = Gtk.Entry()
        self.search_entry.set_placeholder_text("Search clipboard history… (e.g. type:url, pinned:yes)")
        self.search_entry.set_icon_from_icon_name(Gtk.EntryIconPosition.SECONDARY, "edit-clear-symbolic")
        self.search_entry.set_icon_tooltip_text(Gtk.EntryIconPosition.SECONDARY, "Clear search filter")
        self.search_entry.connect("icon-press", lambda entry, icon_pos, event: entry.set_text(""))
        self.search_entry.connect("changed", self._on_search_changed)
        self.search_entry.connect("key-press-event", self._on_search_key)
        self.search_entry.set_margin_bottom(12)
        root.pack_start(self.search_entry, False, False, 0)

        # Scrollable card list
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)

        self.list_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.list_box.set_can_focus(True)
        scroll.add(self.list_box)
        root.pack_start(scroll, True, True, 0)

        # Footer shortcuts
        footer = Gtk.Label(
            label="↑↓ Cards  ←→ Tabs  Enter Copy  O Open URL  P Pin  S Snippet  M Merge  T Tab  E Export  I Import  Del Remove  Esc Close"
        )
        footer.get_style_context().add_class("footer-label")
        footer.set_margin_top(12)
        root.pack_end(footer, False, False, 0)

    # ---- Data loading ----

    def _make_traffic_light(self, kind, base, hover, glyph):
        btn = Gtk.Button(label=glyph)
        btn.set_size_request(13, 13)
        ctx = btn.get_style_context()
        ctx.add_class("traffic-light")
        ctx.add_class(f"traffic-{kind}")
        # Per-button dynamic colors (GTK CSS can't do variables)
        provider = Gtk.CssProvider()
        css = (f".traffic-{kind} {{ background-color: {base}; border-color: rgba(0,0,0,0.35); }} "
               f".traffic-{kind}:hover {{ background-color: {hover}; }}").encode()
        provider.load_from_data(css)
        ctx.add_provider(provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        btn.set_can_focus(False)
        return btn

    def _on_titlebar_press(self, widget, event):
        if event.button == 1:
            self.begin_move_drag(event.button, event.x_root, event.y_root, event.time)
        return True

    def _on_titlebar_close(self, _btn):
        self.destroy()
        Gtk.main_quit()

    def _on_titlebar_minimize(self, _btn):
        self.iconify()

    def _on_titlebar_maximize(self, _btn):
        if self.is_maximized():
            self.unmaximize()
        else:
            self.maximize()

    def _refresh_stats(self):
        stats = get_clipboard_stats()
        db_mb = stats["db_size"] / (1024 * 1024)
        db_txt = f"{db_mb:.1f}MB" if db_mb >= 1 else f"{stats['db_size'] / 1024:.0f}KB"
        oldest_txt = format_age(stats["oldest_age"]) if stats["oldest_age"] is not None else "—"
        self.stats_label.set_text(
            f"Today: {stats['today']}  •  Clips: {stats['total']}  •  "
            f"Snippets: {stats['snippets']}  •  Images: {stats['images']}  •  "
            f"DB: {db_txt}  •  Oldest: {oldest_txt}"
        )

    def _set_type_filter(self, t):
        self.type_filter = t
        for btn_type, btn in self.type_buttons.items():
            ctx = btn.get_style_context()
            if btn_type == t:
                ctx.add_class("active-filter")
            else:
                ctx.remove_class("active-filter")
        self._apply_filter()

    def _switch_view(self, view):
        self.current_view = view
        self.merge_mode = False
        self.selected_indices.clear()
        self.mode_label.set_text("")
        # Update tab styling
        h_ctx = self.btn_history.get_style_context()
        s_ctx = self.btn_snippets.get_style_context()
        if view == "history":
            h_ctx.add_class("active-filter")
            s_ctx.remove_class("active-filter")
        else:
            s_ctx.add_class("active-filter")
            h_ctx.remove_class("active-filter")
        self._load_items()

    def _load_items(self):
        if self.current_view == "snippets":
            self.all_items = fetch_snippets()
        else:
            self.all_items = fetch_history()
        self._apply_filter()

    def _apply_filter(self):
        query = self.search_entry.get_text().strip().lower()
        text_query = query
        type_op = None
        pinned_op = None
        if query:
            tokens = query.split()
            remain = []
            for tok in tokens:
                if tok.startswith("type:"):
                    t = tok[5:]
                    if t in ("url", "email", "code", "number", "image", "text", "snippet"):
                        type_op = t
                    continue
                if tok.startswith("pinned:"):
                    v = tok[7:]
                    pinned_op = v in ("yes", "1", "true")
                    continue
                remain.append(tok)
            text_query = " ".join(remain)

        items = list(self.all_items)
        if type_op:
            items = [it for it in items if it.get("type") == type_op]
        elif self.type_filter:
            items = [it for it in items if it.get("type") == self.type_filter]
        if pinned_op is not None:
            items = [it for it in items if it.get("pinned") is pinned_op]
        if text_query:
            items = [
                it for it in items
                if text_query in it["content"].lower()
                or (it.get("label") or "").lower().find(text_query) >= 0
            ]

        self.filtered_items = items
        n = len(self.filtered_items)
        self.count_label.set_text(f"{n} item{'s' if n != 1 else ''}")
        self.focused_idx = 0 if n > 0 else -1
        self._render_cards()

    # ---- Card rendering ----

    def _render_cards(self):
        # Clear existing cards
        for child in self.list_box.get_children():
            self.list_box.remove(child)
        self.card_widgets.clear()

        if not self.filtered_items:
            empty = Gtk.Label(label="No clipboard history yet.\nCopy something to get started!")
            empty.get_style_context().add_class("empty-label")
            empty.set_justify(Gtk.Justification.CENTER)
            empty.set_valign(Gtk.Align.CENTER)
            empty.set_vexpand(True)
            self.list_box.pack_start(empty, True, True, 40)
            self.list_box.show_all()
            return

        for idx, item in enumerate(self.filtered_items):
            event_box = Gtk.EventBox()
            card = self._make_card(item, idx)
            event_box.add(card)
            # Hover focuses the card (mouse acts like keyboard focus)
            event_box.connect("enter-notify-event", self._on_card_hover, idx)
            # Click to copy
            event_box.connect("button-press-event", self._on_card_click, idx)
            self.list_box.pack_start(event_box, False, False, 0)
            self.card_widgets.append(card)

        self.list_box.show_all()

    def _make_card(self, item, idx):
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        ctx = card.get_style_context()
        ctx.add_class("clip-card")
        
        if idx == self.focused_idx:
            ctx.add_class("focused")
            
        if idx in self.selected_indices:
            ctx.add_class("selected")

        # Top row: badge + age
        top_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)

        badge_text = TYPE_BADGES.get(item["type"], "TEXT")
        if item["pinned"]:
            badge_text = "PINNED"
        
        # Override badge text for custom snippet label if present
        if item["type"] == "snippet" and item.get("label"):
            badge_text = f"{item['label']}".upper()
            
        badge = Gtk.Label(label=badge_text)
        badge.get_style_context().add_class("clip-badge")
        badge.get_style_context().add_class(f"badge-{item['type']}")
        if item["pinned"]:
            badge.get_style_context().add_class("clip-badge-pinned")
        top_row.pack_start(badge, False, False, 0)

        # Smart URL label: show the domain next to the badge
        domain_label = None
        if item["type"] == "url":
            try:
                host = urlparse(item["content"].strip()).netloc
                if host:
                    domain_label = Gtk.Label(label=host)
                    domain_label.get_style_context().add_class("clip-domain")
                    top_row.pack_start(domain_label, False, False, 0)
            except Exception:
                pass

        meta_parts = []
        if item["type"] not in ("image", "snippet"):
            t_str = item["content"].strip()
            w_cnt = len(t_str.split())
            c_cnt = len(t_str)
            meta_parts.append(f"{w_cnt}w · {c_cnt}c")
        meta_parts.append(format_age(item["age_s"]))

        age_label = Gtk.Label(label="  •  ".join(meta_parts))
        age_label.get_style_context().add_class("clip-meta")
        age_label.set_halign(Gtk.Align.END)
        top_row.pack_end(age_label, False, False, 0)

        card.pack_start(top_row, False, False, 0)

        # Content preview or Image Thumbnail
        if item["type"] == "image":
            # Load and display a scaled aspect-ratio thumbnail of the screenshot
            img_widget = Gtk.Image()
            try:
                if os.path.exists(item["content"]):
                    pixbuf = GdkPixbuf.Pixbuf.new_from_file(item["content"])
                    w = pixbuf.get_width()
                    h = pixbuf.get_height()
                    scale = min(400.0 / w, 100.0 / h, 1.0)
                    new_w = max(1, int(w * scale))
                    new_h = max(1, int(h * scale))
                    scaled_pixbuf = pixbuf.scale_simple(new_w, new_h, GdkPixbuf.InterpType.BILINEAR)
                    img_widget.set_from_pixbuf(scaled_pixbuf)
                else:
                    img_widget.set_from_icon_name("image-missing", Gtk.IconSize.DIALOG)
            except Exception:
                img_widget.set_from_icon_name("image-missing", Gtk.IconSize.DIALOG)
            
            img_widget.set_halign(Gtk.Align.START)
            card.pack_start(img_widget, False, False, 0)
        else:
            # Standard text preview
            preview = truncate(item["content"])
            content_label = Gtk.Label(label=preview)
            content_label.set_halign(Gtk.Align.START)
            content_label.set_line_wrap(True)
            content_label.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            content_label.set_max_width_chars(60)
            content_label.set_lines(3)
            content_label.set_ellipsize(Pango.EllipsizeMode.END)
            content_label.get_style_context().add_class("clip-content")

            # Check if it contains a hex color to show color swatch
            color_hex = detect_hex_color(item["content"])
            if color_hex:
                color_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
                
                swatch = Gtk.EventBox()
                swatch.set_size_request(18, 18)
                swatch.get_style_context().add_class("color-swatch")
                
                # Apply color dynamically via local CSS provider (override_background_color is deprecated/ignored)
                color_provider = Gtk.CssProvider()
                css_data = f"* {{ background-color: {color_hex}; }}".encode()
                color_provider.load_from_data(css_data)
                swatch.get_style_context().add_provider(
                    color_provider,
                    Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
                )
                
                color_row.pack_start(swatch, False, False, 0)
                color_row.pack_start(content_label, True, True, 0)
                card.pack_start(color_row, False, False, 0)
            else:
                card.pack_start(content_label, False, False, 0)

        # Expiry progress bar (only for unpinned items)
        if not item["pinned"] and item["expires_in"] is not None and item["retention_s"] > 0:
            fraction = item["expires_in"] / item["retention_s"]
            pbar = Gtk.ProgressBar()
            pbar.set_fraction(fraction)
            if item["expires_in"] < 900:
                pbar.get_style_context().add_class("danger")
            elif item["expires_in"] < 3600:
                pbar.get_style_context().add_class("warning")
            card.pack_start(pbar, False, False, 0)

        # Action bar with clickable option buttons for each card (Copy, Pin, Save, Open, Merge, Uppercase, Delete)
        action_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        action_bar.get_style_context().add_class("card-action-bar")

        btn_copy = Gtk.Button(label="📋 Copy")
        btn_copy.set_can_focus(False)
        btn_copy.get_style_context().add_class("card-action-btn")
        btn_copy.set_tooltip_text("Copy & paste into previous app")
        btn_copy.connect("clicked", lambda _, i=idx: self._on_card_action_copy(i))
        action_bar.pack_start(btn_copy, False, False, 0)

        pin_lbl = "📌 Unpin" if item["pinned"] else "📌 Pin"
        btn_pin = Gtk.Button(label=pin_lbl)
        btn_pin.set_can_focus(False)
        btn_pin.get_style_context().add_class("card-action-btn")
        if item["pinned"]:
            btn_pin.get_style_context().add_class("active-action")
        btn_pin.set_tooltip_text("Toggle pinning (pinned clips don't expire)")
        btn_pin.connect("clicked", lambda _, i=idx: self._on_card_action_pin(i))
        action_bar.pack_start(btn_pin, False, False, 0)

        if item["type"] != "snippet":
            btn_snip = Gtk.Button(label="🔖 Save")
            btn_snip.set_can_focus(False)
            btn_snip.get_style_context().add_class("card-action-btn")
            btn_snip.set_tooltip_text("Save clip permanently as a labeled Snippet")
            btn_snip.connect("clicked", lambda _, i=idx: self._on_card_action_snippet(i))
            action_bar.pack_start(btn_snip, False, False, 0)

        if item["type"] == "url":
            btn_open = Gtk.Button(label="🌐 Open")
            btn_open.set_can_focus(False)
            btn_open.get_style_context().add_class("card-action-btn")
            btn_open.set_tooltip_text("Open URL directly in default browser")
            btn_open.connect("clicked", lambda _, i=idx: self._on_card_action_open(i))
            action_bar.pack_start(btn_open, False, False, 0)

        if item["type"] not in ("image", "snippet"):
            m_lbl = "☑️ Selected" if idx in self.selected_indices else "➕ Merge"
            btn_merge = Gtk.Button(label=m_lbl)
            btn_merge.set_can_focus(False)
            btn_merge.get_style_context().add_class("card-action-btn")
            if idx in self.selected_indices:
                btn_merge.get_style_context().add_class("active-action")
            btn_merge.set_tooltip_text("Select clip for multi-select concatenate merge")
            btn_merge.connect("clicked", lambda _, i=idx: self._on_card_action_merge(i))
            action_bar.pack_start(btn_merge, False, False, 0)

            btn_upper = Gtk.Button(label="🔠 AAA")
            btn_upper.set_can_focus(False)
            btn_upper.get_style_context().add_class("card-action-btn")
            btn_upper.set_tooltip_text("Copy text converted to ALL UPPERCASE")
            btn_upper.connect("clicked", lambda _, i=idx: self._on_card_action_uppercase(i))
            action_bar.pack_start(btn_upper, False, False, 0)

        btn_del = Gtk.Button(label="🗑️")
        btn_del.set_can_focus(False)
        btn_del.get_style_context().add_class("card-action-btn")
        btn_del.get_style_context().add_class("danger-action")
        btn_del.set_tooltip_text("Delete item from database")
        btn_del.connect("clicked", lambda _, i=idx: self._on_card_action_delete(i))
        action_bar.pack_end(btn_del, False, False, 0)

        card.pack_start(action_bar, False, False, 0)

        # Hover tooltip: show the full clip content
        if item["type"] == "image":
            tip = item["content"]
        else:
            tip = item["content"]
        if len(tip) > 1500:
            tip = tip[:1500] + "\n… (content truncated)"
        card.set_tooltip_text(tip)

        return card

    # ---- Focus management ----

    def _update_focus(self):
        for i, card in enumerate(self.card_widgets):
            ctx = card.get_style_context()
            if i == self.focused_idx:
                ctx.add_class("focused")
            else:
                ctx.remove_class("focused")

        # Scroll focused card into view
        if 0 <= self.focused_idx < len(self.card_widgets):
            card = self.card_widgets[self.focused_idx]
            parent_scroll = self.list_box.get_parent()  # ScrolledWindow
            if parent_scroll:
                adj = parent_scroll.get_vadjustment()
                if adj:
                    page = adj.get_page_size()
                    val = adj.get_value()
                    card_h = card.get_allocated_height()
                    # Translate into list_box space (cards are wrapped in EventBoxes)
                    x, card_top = card.translate_coordinates(self.list_box, 0, 0)
                    if x is None:
                        return
                    card_bot = card_top + card_h
                    if card_bot > val + page:
                        adj.set_value(card_bot - page)
                    elif card_top < val:
                        adj.set_value(card_top)

    # ---- Actions ----

    def _action_copy(self):
        if 0 <= self.focused_idx < len(self.filtered_items):
            item = self.filtered_items[self.focused_idx]
            copy_to_clipboard(item)
            self.pasted = True
            # Keep the UI open — only the user closes it (Esc)
            txt = "✓ Copied"
            if item.get("type") == "url":
                try:
                    txt += f" — {urlparse(item['content'].strip()).netloc}"
                except Exception:
                    pass
            self.mode_label.set_text(txt if not self.merge_mode else "[Merge Mode] " + txt)
            GLib.timeout_add(1400, lambda: self._clear_mode_label())
            # Shift focus to the next item (tab-like progression), wrapping at the end
            if len(self.filtered_items) > 1:
                self.focused_idx = (self.focused_idx + 1) % len(self.filtered_items)
                self._update_focus()

    def _action_pin(self):
        if self.current_view == "snippets":
            return
        if 0 <= self.focused_idx < len(self.filtered_items):
            item = self.filtered_items[self.focused_idx]
            toggle_pin(item["id"], item["pinned"])
            self._load_items()

    def _action_delete(self):
        if 0 <= self.focused_idx < len(self.filtered_items):
            item = self.filtered_items[self.focused_idx]
            if self.current_view == "snippets":
                delete_snippet(item["id"])
            else:
                delete_item(item["id"])
            self._load_items()
            if self.focused_idx >= len(self.filtered_items):
                self.focused_idx = max(0, len(self.filtered_items) - 1)
            self._update_focus()
            self._refresh_stats()

    def _action_save_snippet(self):
        if 0 <= self.focused_idx < len(self.filtered_items):
            item = self.filtered_items[self.focused_idx]
            if item["type"] == "image":
                return
            
            dialog = Gtk.MessageDialog(
                transient_for=self,
                flags=Gtk.DialogFlags.MODAL,
                message_type=Gtk.MessageType.QUESTION,
                buttons=Gtk.ButtonsType.OK_CANCEL,
                text="Save as Snippet"
            )
            dialog.set_default_size(300, -1)
            self._dialog_open = True
            
            content_area = dialog.get_content_area()
            
            desc = Gtk.Label(label="Enter a label for this snippet:")
            desc.set_halign(Gtk.Align.START)
            content_area.pack_start(desc, False, False, 6)
            
            entry = Gtk.Entry()
            # Suggest a label based on first 30 chars of the content
            suggested = item["content"].strip().replace("\n", " ")[:30]
            entry.set_text(suggested)
            entry.set_activates_default(True)
            content_area.pack_start(entry, False, False, 6)
            
            dialog.show_all()
            dialog.set_default_response(Gtk.ResponseType.OK)
            
            response = dialog.run()
            label_text = entry.get_text().strip()
            dialog.destroy()
            self._dialog_open = False
            
            if response == Gtk.ResponseType.OK and label_text:
                save_snippet(label_text, item["content"])
                self._refresh_stats()

    def _action_open_url(self):
        if not (0 <= self.focused_idx < len(self.filtered_items)):
            return
        item = self.filtered_items[self.focused_idx]
        if item.get("type") != "url":
            self.mode_label.set_text("Only URL clips can be opened")
            GLib.timeout_add(1800, lambda: self.mode_label.set_text(""))
            return
        url = item["content"].strip()
        try:
            subprocess.Popen(["xdg-open", url],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as exc:
            print(f"[clipy-menu] open url error: {exc}", file=sys.stderr)
            return
        self.destroy()
        Gtk.main_quit()

    def _ask_merge_separator(self):
        dialog = Gtk.Dialog(
            title="Custom Merge",
            transient_for=self,
            flags=Gtk.DialogFlags.MODAL,
        )
        dialog.add_buttons("Cancel", Gtk.ResponseType.CANCEL,
                           "Merge", Gtk.ResponseType.OK)
        dialog.set_default_size(320, -1)
        self._dialog_open = True

        content = dialog.get_content_area()
        content.set_spacing(8)
        content.set_margin_top(12)
        content.set_margin_bottom(12)
        content.set_margin_start(12)
        content.set_margin_end(12)

        desc = Gtk.Label(label="Join selected clips with:")
        desc.set_halign(Gtk.Align.START)
        content.pack_start(desc, False, False, 0)

        combo = Gtk.ComboBoxText()
        for label, _sep in [("New line", "\n"), ("Comma", ", "),
                            ("Space", " "), ("Tab", "\t"), ("Semicolon", "; ")]:
            combo.append_text(label)
        combo.set_active(0)
        content.pack_start(combo, False, False, 0)

        custom = Gtk.Entry()
        custom.set_placeholder_text("Or type a custom separator…")
        content.pack_start(custom, False, False, 0)

        dialog.show_all()
        dialog.set_default_response(Gtk.ResponseType.OK)
        response = dialog.run()
        separator = None
        if response == Gtk.ResponseType.OK:
            custom_text = custom.get_text()
            if custom_text.strip():
                separator = custom_text
            else:
                separator = ["\n", ", ", " ", "\t", "; "][combo.get_active()]
        dialog.destroy()
        self._dialog_open = False
        return separator

    def _export_backup(self):
        chooser = Gtk.FileChooserDialog(
            title="Export Clipy Backup",
            transient_for=self,
            action=Gtk.FileChooserAction.SAVE,
        )
        chooser.add_buttons("Cancel", Gtk.ResponseType.CANCEL,
                            "Export", Gtk.ResponseType.OK)
        chooser.set_current_name(f"clipy-backup-{time.strftime('%Y%m%d-%H%M%S')}.json")
        self._dialog_open = True
        resp = chooser.run()
        path = chooser.get_filename() if resp == Gtk.ResponseType.OK else None
        chooser.destroy()
        self._dialog_open = False
        if not path:
            return
        try:
            conn = sqlite3.connect(DB_FILE)
            clips = conn.execute(
                "SELECT content, created_at, pinned, content_type FROM clipboard_history"
            ).fetchall()
            snips = conn.execute(
                "SELECT label, content, created_at FROM snippets"
            ).fetchall()
            conn.close()
            data = {
                "app": "clipy",
                "exported_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "clips": [{"content": c[0], "created_at": c[1],
                           "pinned": bool(c[2]), "type": c[3]} for c in clips],
                "snippets": [{"label": s[0], "content": s[1],
                              "created_at": s[2]} for s in snips],
            }
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            self.mode_label.set_text("Backup exported")
        except Exception as exc:
            print(f"[clipy-menu] export error: {exc}", file=sys.stderr)
            self.mode_label.set_text("Export failed")
        GLib.timeout_add(1800, lambda: self.mode_label.set_text(""))
        self._refresh_stats()

    def _import_backup(self):
        chooser = Gtk.FileChooserDialog(
            title="Import Clipy Backup",
            transient_for=self,
            action=Gtk.FileChooserAction.OPEN,
        )
        chooser.add_buttons("Cancel", Gtk.ResponseType.CANCEL,
                            "Import", Gtk.ResponseType.OK)
        self._dialog_open = True
        resp = chooser.run()
        path = chooser.get_filename() if resp == Gtk.ResponseType.OK else None
        chooser.destroy()
        self._dialog_open = False
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            conn = sqlite3.connect(DB_FILE)
            imported_clips = imported_snips = 0
            for c in data.get("clips", []):
                cur = conn.execute(
                    """INSERT OR IGNORE INTO clipboard_history
                       (content, created_at, pinned, content_type)
                       VALUES (?, ?, ?, ?)""",
                    (c.get("content", ""), c.get("created_at"),
                     1 if c.get("pinned") else 0, c.get("type", "text")))
                imported_clips += cur.rowcount
            for s in data.get("snippets", []):
                cur = conn.execute(
                    """INSERT OR IGNORE INTO snippets (label, content, created_at)
                       VALUES (?, ?, ?)""",
                    (s.get("label", ""), s.get("content", ""), s.get("created_at")))
                imported_snips += cur.rowcount
            conn.commit()
            conn.close()
            self.mode_label.set_text(
                f"Imported {imported_clips} clip(s), {imported_snips} snippet(s)"
            )
        except Exception as exc:
            print(f"[clipy-menu] import error: {exc}", file=sys.stderr)
            self.mode_label.set_text("Import failed")
        GLib.timeout_add(1800, lambda: self.mode_label.set_text(""))
        self._load_items()
        self._refresh_stats()

    def _toggle_selection(self, idx):
        if 0 <= idx < len(self.filtered_items):
            item = self.filtered_items[idx]
            if item["type"] == "image":
                return  # Images cannot be merged
            if idx in self.selected_indices:
                self.selected_indices.remove(idx)
            else:
                self.selected_indices.add(idx)
            
            if self.selected_indices:
                self.btn_merge_now.set_label(f"⚡ Merge ({len(self.selected_indices)})")
                self.btn_merge_now.set_visible(True)
            else:
                self.btn_merge_now.set_visible(False)

            self._render_cards()

    def _execute_merge(self):
        if not self.selected_indices:
            self.mode_label.set_text("[Merge Mode] Select 1+ clips first")
            return

        separator = "\n"
        if len(self.selected_indices) > 1:
            sep = self._ask_merge_separator()
            if sep is None:
                return  # user cancelled separator dialog

            separator = sep

        sorted_indices = sorted(list(self.selected_indices))
        selected_texts = [self.filtered_items[i]["content"] for i in sorted_indices if i < len(self.filtered_items)]
        if not selected_texts:
            return

        merged_text = separator.join(selected_texts)
        merged_item = {"type": "text", "content": merged_text}
        copy_to_clipboard(merged_item)

        content_type = classify_content(merged_text)
        save_text_clip(merged_text, content_type)

        self.merge_mode = False
        self.selected_indices.clear()
        if hasattr(self, "btn_merge_now"):
            self.btn_merge_now.set_visible(False)
        self.mode_label.set_text("✓ Merged & Copied to Clipboard")
        GLib.timeout_add(2000, lambda: self._clear_mode_label())

        # Reload history items so the new merged card appears at the top
        self._load_items()
        self._refresh_stats()

        # Focus the newly created merged clip
        new_idx = 0
        for idx, item in enumerate(self.filtered_items):
            if item["content"] == merged_text:
                new_idx = idx
                break

        self.focused_idx = new_idx
        self._update_focus()

    # ---- Event handlers ----

    def _clear_mode_label(self):
        if self.merge_mode:
            self.mode_label.set_text("[Merge Mode] Select cards, Enter to merge")
        else:
            self.mode_label.set_text("")
        return False

    def _on_focus_out(self, widget, event):
        # Keep the window open — do not auto-close on focus loss
        return True

    def _on_search_changed(self, entry):
        self._apply_filter()

    def _on_card_hover(self, widget, event, idx):
        if self._hover_locked:
            return False
        if 0 <= idx < len(self.filtered_items) and idx != self.focused_idx:
            self.focused_idx = idx
            self._update_focus()
        return False

    def _show_card_context_menu(self, event, idx):
        if not (0 <= idx < len(self.filtered_items)):
            return
        item = self.filtered_items[idx]
        menu = Gtk.Menu()

        item_copy = Gtk.MenuItem(label="📋 Copy & Paste")
        item_copy.connect("activate", lambda _: self._on_card_action_copy(idx))
        menu.append(item_copy)

        pin_title = "📌 Unpin Clip" if item["pinned"] else "📌 Pin Clip"
        item_pin = Gtk.MenuItem(label=pin_title)
        item_pin.connect("activate", lambda _: self._on_card_action_pin(idx))
        menu.append(item_pin)

        if item["type"] != "snippet":
            item_snip = Gtk.MenuItem(label="🔖 Save as Snippet")
            item_snip.connect("activate", lambda _: self._on_card_action_snippet(idx))
            menu.append(item_snip)

        if item["type"] == "url":
            item_open = Gtk.MenuItem(label="🌐 Open in Browser")
            item_open.connect("activate", lambda _: self._on_card_action_open(idx))
            menu.append(item_open)

        if item["type"] not in ("image", "snippet"):
            menu.append(Gtk.SeparatorMenuItem())
            item_upper = Gtk.MenuItem(label="🔠 Copy as UPPERCASE")
            item_upper.connect("activate", lambda _: self._on_card_action_uppercase(idx))
            menu.append(item_upper)

            item_lower = Gtk.MenuItem(label="🔡 Copy as lowercase")
            item_lower.connect("activate", lambda _: self._on_card_action_lowercase(idx))
            menu.append(item_lower)

            item_trim = Gtk.MenuItem(label="✂️ Copy Trimmed Text")
            item_trim.connect("activate", lambda _: self._on_card_action_trim(idx))
            menu.append(item_trim)

        menu.append(Gtk.SeparatorMenuItem())
        item_del = Gtk.MenuItem(label="🗑️ Delete Item")
        item_del.connect("activate", lambda _: self._on_card_action_delete(idx))
        menu.append(item_del)

        menu.show_all()
        menu.popup_at_pointer(event)

    def _on_card_action_copy(self, idx):
        if 0 <= idx < len(self.filtered_items):
            self.focused_idx = idx
            self._update_focus()
            self._action_copy()

    def _on_card_action_pin(self, idx):
        if 0 <= idx < len(self.filtered_items):
            self.focused_idx = idx
            self._action_pin()

    def _on_card_action_snippet(self, idx):
        if 0 <= idx < len(self.filtered_items):
            self.focused_idx = idx
            self._action_save_snippet()

    def _on_card_action_open(self, idx):
        if 0 <= idx < len(self.filtered_items):
            self.focused_idx = idx
            self._action_open_url()

    def _on_card_action_merge(self, idx):
        if 0 <= idx < len(self.filtered_items):
            self.focused_idx = idx
            if not self.merge_mode:
                self.merge_mode = True
                self.mode_label.set_text("[Merge Mode] Select cards, Enter to merge")
            self._toggle_selection(idx)

    def _on_card_action_uppercase(self, idx):
        if 0 <= idx < len(self.filtered_items):
            item = self.filtered_items[idx]
            if item["type"] != "image":
                mod_item = dict(item)
                mod_item["content"] = item["content"].upper()
                copy_to_clipboard(mod_item)
                self.pasted = True
                self.mode_label.set_text("✓ Copied as UPPERCASE")
                GLib.timeout_add(1400, lambda: self._clear_mode_label())

    def _on_card_action_lowercase(self, idx):
        if 0 <= idx < len(self.filtered_items):
            item = self.filtered_items[idx]
            if item["type"] != "image":
                mod_item = dict(item)
                mod_item["content"] = item["content"].lower()
                copy_to_clipboard(mod_item)
                self.pasted = True
                self.mode_label.set_text("✓ Copied as lowercase")
                GLib.timeout_add(1400, lambda: self._clear_mode_label())

    def _on_card_action_trim(self, idx):
        if 0 <= idx < len(self.filtered_items):
            item = self.filtered_items[idx]
            if item["type"] != "image":
                mod_item = dict(item)
                mod_item["content"] = item["content"].strip()
                copy_to_clipboard(mod_item)
                self.pasted = True
                self.mode_label.set_text("✓ Copied Trimmed Text")
                GLib.timeout_add(1400, lambda: self._clear_mode_label())

    def _on_card_action_delete(self, idx):
        if 0 <= idx < len(self.filtered_items):
            self.focused_idx = idx
            self._action_delete()

    def _on_card_click(self, widget, event, idx):
        if event.button == 3:  # Right-click context menu
            self.focused_idx = idx
            self._update_focus()
            self._show_card_context_menu(event, idx)
            return True
        if self.merge_mode:
            self._toggle_selection(idx)
        else:
            self.focused_idx = idx
            self._update_focus()
            self._action_copy()
        return True

    def _cycle_type_filter(self, delta: int):
        if self.current_view != "snippets":
            cur_i = self.type_order.index(self.type_filter) if self.type_filter in self.type_order else 0
            next_t = self.type_order[(cur_i + delta) % len(self.type_order)]
            self._set_type_filter(next_t)

    def _on_search_key(self, widget, event):
        key = Gdk.keyval_name(event.keyval)
        n = len(self.filtered_items)
        has_ctrl_alt = bool(event.state & (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.MOD1_MASK))

        if key in ("Right", "KP_Right"):
            text = self.search_entry.get_text()
            pos = self.search_entry.get_position()
            if not text or pos == len(text) or has_ctrl_alt:
                self._cycle_type_filter(1)
                return True

        if key in ("Left", "KP_Left"):
            text = self.search_entry.get_text()
            pos = self.search_entry.get_position()
            if not text or pos == 0 or has_ctrl_alt:
                self._cycle_type_filter(-1)
                return True

        if key == "Down" and n > 0:
            self.focused_idx = 0
            self._update_focus()
            self.list_box.grab_focus()
            return True

        if key == "Return":
            if self.merge_mode:
                self._execute_merge()
                return True
            elif self.focused_idx >= 0:
                self._action_copy()
                return True

        if key == "Escape":
            self.destroy()
            Gtk.main_quit()
            return True

        return False

    def _on_key_press(self, widget, event):
        if self.search_entry.has_focus():
            return False

        key = Gdk.keyval_name(event.keyval)
        n = len(self.filtered_items)

        if key == "Down" and n > 0:
            self.focused_idx = min(self.focused_idx + 1, n - 1)
            self._update_focus()
            return True
        elif key == "Up":
            if self.focused_idx <= 0:
                self.focused_idx = 0 if n > 0 else -1
                self.search_entry.grab_focus()
            else:
                self.focused_idx -= 1
            self._update_focus()
            return True
        elif key in ("Right", "KP_Right"):
            self._cycle_type_filter(1)
            return True
        elif key in ("Left", "KP_Left"):
            self._cycle_type_filter(-1)
            return True
        elif key == "Return":
            if self.merge_mode:
                self._execute_merge()
            else:
                self._action_copy()
            return True
        elif key in ("p", "P"):
            self._action_pin()
            return True
        elif key in ("o", "O"):
            self._action_open_url()
            return True
        elif key in ("e", "E"):
            self._export_backup()
            return True
        elif key in ("i", "I"):
            self._import_backup()
            return True
        elif key in ("s", "S"):
            self._action_save_snippet()
            return True
        elif key in ("m", "M"):
            if self.current_view != "snippets":
                self.merge_mode = not self.merge_mode
                self.selected_indices.clear()
                self.mode_label.set_text("[Merge Mode] Select cards, Enter to merge" if self.merge_mode else "")
                self._render_cards()
            return True
        elif key in ("t", "T"):
            new_view = "snippets" if self.current_view == "history" else "history"
            self._switch_view(new_view)
            return True
        elif key == "space" and self.merge_mode:
            self._toggle_selection(self.focused_idx)
            return True
        elif key == "Delete":
            self._action_delete()
            return True
        elif key == "slash":
            self.search_entry.grab_focus()
            return True
        elif key == "Escape":
            self.destroy()
            Gtk.main_quit()
            return True

        return False

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    # Set program name so GNOME matches it to clipy.desktop (StartupWMClass)
    GLib.set_prgname('Clipy')
    GLib.set_application_name('Clipy')

    # Apply CSS
    css_provider = Gtk.CssProvider()
    css_provider.load_from_data(CSS)
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(),
        css_provider,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
    )

    win = ClipyWindow()
    win.connect("destroy", Gtk.main_quit)
    win.show_all()

    # Give focus to search by default
    win.search_entry.grab_focus()

    Gtk.main()

    # After the GTK loop exits, paste-and-close (only when a copy was made)
    if win.pasted:
        paste_to_previous_window()


if __name__ == '__main__':
    main()
