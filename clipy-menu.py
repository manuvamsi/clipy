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

import os
import re
import sys
import shutil
import sqlite3
import subprocess
import time

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
from gi.repository import Gtk, Gdk, GLib, Pango, GdkPixbuf

# ---------------------------------------------------------------------------
# Paths & config
# ---------------------------------------------------------------------------
DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "clipy.db")
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
    "url":    "🔗 URL",
    "email":  "📧 Email",
    "code":   "💻 Code",
    "number": "🔢 Number",
    "text":   "📝 Text",
}

# ---------------------------------------------------------------------------
# Color detection for hex color preview
# ---------------------------------------------------------------------------
HEX_COLOR_RE = re.compile(r'#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b')

def detect_hex_color(text):
    """Return the first hex color found in text, or None."""
    m = HEX_COLOR_RE.search(text.strip())
    return m.group(0) if m else None
# GTK CSS — glassmorphic / Fluent dark theme
# ---------------------------------------------------------------------------
CSS = b"""
/* ---- window ---- */
window {
    background-color: #0d0b1a;
}

/* ---- search entry ---- */
entry {
    background-color: rgba(255, 255, 255, 0.06);
    border: 1px solid rgba(255, 255, 255, 0.10);
    border-radius: 10px;
    color: #f3f4f6;
    padding: 10px 14px;
    font-family: 'Outfit', 'Cantarell', sans-serif;
    font-size: 14px;
    caret-color: #a78bfa;
    min-height: 20px;
}
entry:focus {
    border-color: rgba(139, 92, 246, 0.50);
    box-shadow: 0 0 8px rgba(139, 92, 246, 0.25);
}

/* ---- card (each history item) ---- */
.clip-card {
    background-color: #1a1730;
    border: 1px solid #2a2545;
    border-radius: 12px;
    padding: 12px 14px;
    transition: 200ms ease;
}
.clip-card:hover {
    background-color: #211e38;
    border-color: #3a3560;
}
.clip-card.focused {
    background-color: #1e1840;
    border-color: #7c5cdb;
    box-shadow: 0 0 12px rgba(139, 92, 246, 0.30);
}

/* ---- text inside cards ---- */
.clip-content {
    color: #e5e7eb;
    font-family: 'Outfit', 'Cantarell', sans-serif;
    font-size: 13px;
}
.clip-meta {
    color: #9ca3af;
    font-size: 11px;
}
.clip-badge {
    font-size: 10px;
    padding: 2px 8px;
    border-radius: 6px;
    background-color: rgba(255, 255, 255, 0.06);
    color: #c084fc;
}
.clip-badge-pinned {
    color: #fbbf24;
}

/* ---- header / title ---- */
.header-title {
    color: #ffffff;
    font-size: 17px;
    font-weight: 700;
    font-family: 'Outfit', 'Cantarell', sans-serif;
}
.header-subtitle {
    color: #9ca3af;
    font-size: 11px;
    font-family: 'Outfit', 'Cantarell', sans-serif;
}
.header-count {
    color: #9ca3af;
    font-size: 12px;
    padding: 3px 10px;
    border-radius: 12px;
    background-color: rgba(255, 255, 255, 0.05);
    border: 1px solid rgba(255, 255, 255, 0.08);
}

/* ---- expiry progress bar ---- */
progressbar trough {
    background-color: rgba(255, 255, 255, 0.04);
    border-radius: 2px;
    min-height: 3px;
}
progressbar progress {
    border-radius: 2px;
    min-height: 3px;
    background-color: #8b5cf6;
}
progressbar.warning progress {
    background-color: #f59e0b;
}
progressbar.danger progress {
    background-color: #ef4444;
}

/* ---- scrollbar ---- */
scrolledwindow scrollbar slider {
    background-color: rgba(255, 255, 255, 0.10);
    border-radius: 10px;
    min-width: 6px;
}
scrolledwindow scrollbar slider:hover {
    background-color: rgba(255, 255, 255, 0.20);
}
scrolledwindow scrollbar {
    background-color: transparent;
}

/* ---- footer ---- */
.footer-label {
    color: #6b7280;
    font-size: 10px;
    font-family: 'Outfit', 'Cantarell', sans-serif;
}

/* ---- empty state ---- */
.empty-label {
    color: #6b7280;
    font-size: 14px;
    font-family: 'Outfit', 'Cantarell', sans-serif;
}

/* ---- color swatch ---- */
.color-swatch {
    border-radius: 4px;
    min-width: 18px;
    min-height: 18px;
    border: 1px solid rgba(255, 255, 255, 0.20);
}

/* ---- merge mode selected card ---- */
.clip-card.selected {
    background-color: #1a2535;
    border-color: #10b981;
    box-shadow: 0 0 8px rgba(16, 185, 129, 0.25);
}

/* ---- stats bar ---- */
.stats-bar {
    color: #6b7280;
    font-size: 10px;
    font-family: 'Outfit', 'Cantarell', sans-serif;
    padding: 4px 0;
}
.stats-bar-highlight {
    color: #a78bfa;
    font-size: 10px;
}

/* ---- mode indicator ---- */
.mode-label {
    color: #10b981;
    font-size: 11px;
    font-weight: 700;
    font-family: 'Outfit', 'Cantarell', sans-serif;
}

/* ---- filter tabs ---- */
.filter-btn {
    background-color: transparent;
    border: none;
    color: #6b7280;
    font-size: 11px;
    font-family: 'Outfit', 'Cantarell', sans-serif;
    padding: 4px 10px;
    border-radius: 8px;
}
.filter-btn:hover {
    background-color: #1a1730;
    color: #e5e7eb;
}
.filter-btn.active-filter {
    background-color: #1e1840;
    color: #c084fc;
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
        c.execute("""SELECT content_type, COUNT(*) FROM clipboard_history
                     GROUP BY content_type ORDER BY COUNT(*) DESC""")
        by_type = {r[0]: r[1] for r in c.fetchall()}
        c.execute("SELECT COUNT(*) FROM snippets")
        snippets = c.fetchone()[0]
        conn.close()
        return {"total": total, "today": today, "by_type": by_type, "snippets": snippets}
    except Exception:
        return {"total": 0, "today": 0, "by_type": {}, "snippets": 0}

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
            LIMIT -1 OFFSET 50
        ''')
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
                LIMIT -1 OFFSET 50
            )
        ''')
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
        self.set_resizable(False)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.set_type_hint(Gdk.WindowTypeHint.DIALOG)
        self.set_keep_above(True)
        self.set_skip_taskbar_hint(True)

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

        # Layout
        self._build_ui()
        self._load_items()

    # ---- UI construction ----

    def _build_ui(self):
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        root.set_margin_top(20)
        root.set_margin_bottom(16)
        root.set_margin_start(20)
        root.set_margin_end(20)
        self.add(root)

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
        self.btn_history.connect("clicked", lambda _: self._switch_view("history"))
        filter_row.pack_start(self.btn_history, False, False, 0)

        self.btn_snippets = Gtk.Button(label="Snippets")
        self.btn_snippets.get_style_context().add_class("filter-btn")
        self.btn_snippets.connect("clicked", lambda _: self._switch_view("snippets"))
        filter_row.pack_start(self.btn_snippets, False, False, 0)

        self.mode_label = Gtk.Label(label="")
        self.mode_label.get_style_context().add_class("mode-label")
        self.mode_label.set_halign(Gtk.Align.END)
        filter_row.pack_end(self.mode_label, False, False, 0)

        root.pack_start(filter_row, False, False, 0)

        # Search
        self.search_entry = Gtk.Entry()
        self.search_entry.set_placeholder_text("Search clipboard history…")
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
            label="↑↓ Nav  Enter Copy  P Pin  S Snippet  M Merge  T Toggle Tab  Del Remove  Esc Close"
        )
        footer.get_style_context().add_class("footer-label")
        footer.set_margin_top(12)
        root.pack_end(footer, False, False, 0)

    # ---- Data loading ----

    def _refresh_stats(self):
        stats = get_clipboard_stats()
        type_parts = "  ".join(f"{TYPE_BADGES.get(k,'📝')[0]} {v}" for k, v in stats["by_type"].items())
        self.stats_label.set_text(
            f"Today: {stats['today']} copies  •  Total: {stats['total']}  •  "
            f"Snippets: {stats['snippets']}  {type_parts}"
        )

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
        if query:
            self.filtered_items = [
                it for it in self.all_items
                if query in it["content"].lower()
                or (it.get("label") or "").lower().find(query) >= 0
            ]
        else:
            self.filtered_items = list(self.all_items)

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
            empty = Gtk.Label(label="📭  No clipboard history yet.\nCopy something to get started!")
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

        badge_text = TYPE_BADGES.get(item["type"], "📝 Text")
        if item["pinned"]:
            badge_text = "📌 Pinned"
        
        # Override badge text for custom snippet label if present
        if item["type"] == "snippet" and item.get("label"):
            badge_text = f"🔖 {item['label']}"
            
        badge = Gtk.Label(label=badge_text)
        badge.get_style_context().add_class("clip-badge")
        if item["pinned"]:
            badge.get_style_context().add_class("clip-badge-pinned")
        top_row.pack_start(badge, False, False, 0)

        age_label = Gtk.Label(label=format_age(item["age_s"]))
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
            alloc = card.get_allocation()
            parent_scroll = self.list_box.get_parent()  # ScrolledWindow
            if parent_scroll:
                adj = parent_scroll.get_vadjustment()
                if adj:
                    page = adj.get_page_size()
                    val = adj.get_value()
                    card_top = alloc.y
                    card_bot = alloc.y + alloc.height
                    if card_bot > val + page:
                        adj.set_value(card_bot - page)
                    elif card_top < val:
                        adj.set_value(card_top)

    # ---- Actions ----

    def _action_copy(self):
        if 0 <= self.focused_idx < len(self.filtered_items):
            item = self.filtered_items[self.focused_idx]
            copy_to_clipboard(item)
            self.destroy()
            Gtk.main_quit()

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
            
            if response == Gtk.ResponseType.OK and label_text:
                save_snippet(label_text, item["content"])
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
            self._render_cards()

    # ---- Event handlers ----

    def _on_focus_out(self, widget, event):
        self.destroy()
        Gtk.main_quit()
        return False

    def _on_search_changed(self, entry):
        self._apply_filter()

    def _on_card_click(self, widget, event, idx):
        if self.merge_mode:
            self._toggle_selection(idx)
        else:
            self.focused_idx = idx
            self._update_focus()
            self._action_copy()
        return True

    def _on_search_key(self, widget, event):
        key = Gdk.keyval_name(event.keyval)
        n = len(self.filtered_items)

        if key == "Down" and n > 0:
            self.focused_idx = 0
            self._update_focus()
            self.list_box.grab_focus()
            return True

        if key == "Return" and self.focused_idx >= 0:
            if self.merge_mode:
                # Fall through to let the main key_press handle the merge action
                return False
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
        elif key == "Return":
            if self.merge_mode:
                if self.selected_indices:
                    # Merge selected text clips in index order
                    sorted_indices = sorted(list(self.selected_indices))
                    selected_texts = [self.filtered_items[i]["content"] for i in sorted_indices]
                    merged_text = "\n".join(selected_texts)
                    merged_item = {"type": "text", "content": merged_text}
                    copy_to_clipboard(merged_item)
                    
                    content_type = classify_content(merged_text)
                    save_text_clip(merged_text, content_type)
                    
                    self.merge_mode = False
                    self.selected_indices.clear()
                    self.mode_label.set_text("")
                    self._load_items()
                    
                    new_idx = 0
                    for idx, item in enumerate(self.filtered_items):
                        if item["content"] == merged_text:
                            new_idx = idx
                            break
                    self.focused_idx = new_idx
                    self._update_focus()
                    self._refresh_stats()
                else:
                    self.merge_mode = False
                    self.mode_label.set_text("")
                    self._render_cards()
            else:
                self._action_copy()
            return True
        elif key in ("p", "P"):
            self._action_pin()
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

    # After the GTK loop exits, attempt paste-and-close
    paste_to_previous_window()


if __name__ == '__main__':
    main()
