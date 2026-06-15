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
import sys
import shutil
import sqlite3
import subprocess
import time

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
from gi.repository import Gtk, Gdk, GLib, Pango

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
# GTK CSS — glassmorphic / Fluent dark theme
# ---------------------------------------------------------------------------
CSS = b"""
/* ---- window ---- */
window {
    background-color: rgba(12, 10, 24, 0.94);
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
    background-color: rgba(255, 255, 255, 0.035);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 12px;
    padding: 12px 14px;
    transition: 200ms ease;
}
.clip-card:hover {
    background-color: rgba(255, 255, 255, 0.06);
    border-color: rgba(255, 255, 255, 0.14);
}
.clip-card.focused {
    background-color: rgba(139, 92, 246, 0.08);
    border-color: rgba(139, 92, 246, 0.45);
    box-shadow: 0 0 12px rgba(139, 92, 246, 0.20);
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
    conn = sqlite3.connect(DB_FILE)
    conn.execute("DELETE FROM clipboard_history WHERE id = ?", (item_id,))
    conn.commit()
    conn.close()


def toggle_pin(item_id, currently_pinned):
    conn = sqlite3.connect(DB_FILE)
    conn.execute("UPDATE clipboard_history SET pinned = ? WHERE id = ?",
                 (0 if currently_pinned else 1, item_id))
    conn.commit()
    conn.close()


def copy_to_clipboard(text):
    try:
        p = subprocess.Popen(['xsel', '-b', '-i'], stdin=subprocess.PIPE, text=True)
        p.communicate(input=text)
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
# Helpers
# ---------------------------------------------------------------------------

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

        # Make the window background transparent for the CSS to take effect
        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        if visual:
            self.set_visual(visual)
        self.set_app_paintable(True)

        # Close on focus-out
        self.connect("focus-out-event", self._on_focus_out)
        self.connect("key-press-event", self._on_key_press)

        # State
        self.all_items = []
        self.filtered_items = []
        self.focused_idx = -1
        self.card_widgets = []

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
        header.set_margin_bottom(14)

        logo_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        title = Gtk.Label(label="📋  Clipy")
        title.set_halign(Gtk.Align.START)
        title.get_style_context().add_class("header-title")
        logo_box.pack_start(title, False, False, 0)

        subtitle = Gtk.Label(label="Clipboard History")
        subtitle.set_halign(Gtk.Align.START)
        subtitle.get_style_context().add_class("header-subtitle")
        logo_box.pack_start(subtitle, False, False, 2)

        header.pack_start(logo_box, True, True, 0)

        self.count_label = Gtk.Label(label="0 items")
        self.count_label.get_style_context().add_class("header-count")
        self.count_label.set_valign(Gtk.Align.CENTER)
        header.pack_end(self.count_label, False, False, 0)

        root.pack_start(header, False, False, 0)

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
        scroll.add(self.list_box)
        root.pack_start(scroll, True, True, 0)

        # Footer shortcuts
        footer = Gtk.Label(
            label="↑↓ Navigate   Enter Copy   P Pin   Del Remove   Esc Close"
        )
        footer.get_style_context().add_class("footer-label")
        footer.set_margin_top(12)
        root.pack_end(footer, False, False, 0)

    # ---- Data loading ----

    def _load_items(self):
        self.all_items = fetch_history()
        self._apply_filter()

    def _apply_filter(self):
        query = self.search_entry.get_text().strip().lower()
        if query:
            self.filtered_items = [
                it for it in self.all_items
                if query in it["content"].lower()
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
            card = self._make_card(item, idx)
            self.list_box.pack_start(card, False, False, 0)
            self.card_widgets.append(card)

        self.list_box.show_all()

    def _make_card(self, item, idx):
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        ctx = card.get_style_context()
        ctx.add_class("clip-card")
        if idx == self.focused_idx:
            ctx.add_class("focused")

        # Top row: badge + age
        top_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)

        badge_text = TYPE_BADGES.get(item["type"], "📝 Text")
        if item["pinned"]:
            badge_text = "📌 Pinned"
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

        # Content preview
        preview = truncate(item["content"])
        content_label = Gtk.Label(label=preview)
        content_label.set_halign(Gtk.Align.START)
        content_label.set_line_wrap(True)
        content_label.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        content_label.set_max_width_chars(60)
        content_label.set_lines(3)
        content_label.set_ellipsize(Pango.EllipsizeMode.END)
        content_label.get_style_context().add_class("clip-content")
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
            copy_to_clipboard(item["content"])
            self.destroy()
            Gtk.main_quit()
            # After GTK loop ends, paste into previous window (handled in main)

    def _action_pin(self):
        if 0 <= self.focused_idx < len(self.filtered_items):
            item = self.filtered_items[self.focused_idx]
            toggle_pin(item["id"], item["pinned"])
            self._load_items()

    def _action_delete(self):
        if 0 <= self.focused_idx < len(self.filtered_items):
            item = self.filtered_items[self.focused_idx]
            delete_item(item["id"])
            self._load_items()
            if self.focused_idx >= len(self.filtered_items):
                self.focused_idx = max(0, len(self.filtered_items) - 1)
            self._update_focus()

    # ---- Event handlers ----

    def _on_focus_out(self, widget, event):
        self.destroy()
        Gtk.main_quit()
        return False

    def _on_search_changed(self, entry):
        self._apply_filter()

    def _on_search_key(self, widget, event):
        key = Gdk.keyval_name(event.keyval)
        if key == "Down" and self.filtered_items:
            self.focused_idx = 0
            self._update_focus()
            # Remove focus from search so global keys work
            self.set_focus(None)
            return True
        if key == "Escape":
            self.destroy()
            Gtk.main_quit()
            return True
        return False

    def _on_key_press(self, widget, event):
        # If search has focus, let it handle most keys
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
                self.focused_idx = -1
                self.search_entry.grab_focus()
            else:
                self.focused_idx -= 1
            self._update_focus()
            return True
        elif key == "Return":
            self._action_copy()
            return True
        elif key in ("p", "P"):
            self._action_pin()
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
