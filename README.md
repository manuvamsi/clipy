# 📋 Clipy — Advanced Clipboard History & Snippet Manager for Linux

A lightweight, native, and feature-rich clipboard history manager for Ubuntu and GNOME-based Linux distributions (supporting both Wayland and X11). Built entirely with Python 3 and GTK 3 (`PyGObject`).

**Zero web frameworks. Zero Electron. Zero bloat.** Just a beautiful, ultra-fast glassmorphic popup that stays out of your way and supercharges your productivity.

---

## ✨ Release Features

| Feature | Description |
|:---|:---|
| 📋 **Gdk-Native Polling** | Replaces old polling methods with native `Gdk.Clipboard` and event-driven updates. Highly reliable on GNOME/Wayland. |
| 🔘 **Per-Card Action Bar** | Every card features clickable inline action buttons: **📋 Copy**, **📌 Pin/Unpin**, **🔖 Save Snippet**, **🌐 Open URL**, **➕ Merge Select**, **🔠 AAA Uppercase**, and **🗑️ Delete**. |
| 🖱️ **Right-Click Context Menu** | Right-click any card to open a GTK popup menu with options including **Copy & Paste**, **Pin**, **Save Snippet**, **Open in Browser**, **UPPERCASE**, **lowercase**, **Trim**, and **Delete**. |
| 🔤 **Text Case Transformations** | One-click text converters to copy text in **ALL CAPS (`🔠 AAA`)**, **lowercase**, or **trimmed** whitespace. |
| 🏷️ **Type Filter Chips & Nav** | Filter clips instantly by type (**ALL**, **URL**, **EMAIL**, **CODE**, **NUMBER**, **IMAGE**). Cycle tabs seamlessly using `←` / `→` arrow keys without accidental copies. |
| 🌐 **Direct URL Launcher** | Press `O` (or click `🌐 Open`) on any URL clip to open it in your default browser via `xdg-open`. Displays web domains (e.g. `github.com`) beside badges. |
| 📸 **Image & Screenshot Capture** | Silently monitors clipboard image targets (like print-screen screenshots). Compares pixel data via **MD5 hashing** to avoid duplicates, saves screenshots to disk, and displays aspect-ratio thumbnails. |
| 📝 **Multi-Select Merge Mode** | Press `M` to toggle Merge Mode, select multiple text clips (`Space` or click **➕ Merge**), and press `Enter` to join them with custom separators (Newline, Comma, Space, Tab, Semicolon, or custom string). |
| 📊 **Word & Character Stats** | Card headers display real-time word count (`w`) and character count (`c`) metadata alongside timestamps. |
| 🏷️ **Saved Snippets View** | Press `S` (or click **🔖 Save**) to save any text clip permanently as a Snippet with a custom label. Toggle between History and Snippets using `T` or top filter tabs. |
| 💾 **JSON Backup & Restore** | Export (`E`) your entire clipboard history and snippets to a JSON backup file, or import (`I`) backups seamlessly across systems. |
| 🔍 **Smart Search & Clear Icon** | Full-text search bar with clear button (`✕`) supporting filter flags like `type:url`, `type:code`, `type:email`, `type:image`, and `pinned:yes`/`pinned:no`. |
| 🎨 **Hex Color Swatches** | Automatically detects HEX color codes (`#HEX`) in text clips and displays a live CSS-rendered color swatch beside the clip. |
| 📊 **Analytics Dashboard** | Live header dashboard showing today's copies, total clip count, saved snippets count, total images, database file size, and oldest clip age. |
| ⏱️ **Automatic GC & Pruning** | Unpinned items automatically expire after 4 hours (configurable). Old image files on disk are automatically cleaned up when items are deleted or pruned. |
| 🔒 **Privacy-First** | Credit cards, API keys (e.g. `sk-`, `ghp_`, `Bearer`), and sensitive passwords are automatically classified and skipped. |
| 📋➡️📄 **Paste-and-Close** | Select any item and press `Enter` to copy it and automatically paste it directly into your previous active application window *(requires `xdotool`)*. |
| 🪟 **Mac-Style Titlebar** | Sleek titlebar with traffic light buttons (Close `✕`, Minimize `−`, Maximize `+`) and native drag-to-move window controls. |

---

## 📸 Architecture & Workflow

```
┌────────────────────────────────────┐
│  You copy text/image (Ctrl+C)      │
└──────────────┬─────────────────────┘
               │
               ▼
┌────────────────────────────────────┐
│  clipy-daemon (systemd user service)│
│  • Detects text/image clipboard    │
│  • Performs MD5 pixel hashing      │
│  • Privacy filtering (API keys)    │
│  • Manages SQLite DB & auto-pruning│
└──────────────┬─────────────────────┘
               │
               │  Press Super+Shift+V
               ▼
┌────────────────────────────────────┐
│  Premium Glassmorphic GTK 3 Popup  │
│  • Inline Action Bars on Cards     │
│  • Right-Click Context Menus       │
│  • Type filtering & Search flags   │
│  • Interactive Merge Mode (M)      │
│  • Direct URL Launcher (O)         │
│  • JSON Backup & Restore (E / I)   │
│  • Enter to copy & paste to window │
└──────────────┬─────────────────────┘
```

---

## 🚀 Installation & Setup

### Prerequisites

- **Ubuntu 22.04+** (or any GNOME/Wayland or GNOME/X11 distro)
- **Python 3.10+** (pre-installed on Ubuntu)
- **python3-gi** (PyGObject bindings for GTK/Gdk)
- **xdotool** (optional: enables paste-and-close feature)

```bash
# Install required system dependencies
sudo apt update
sudo apt install python3-gi xdotool
```

### Install Clipy

1. Clone the repository:
   ```bash
   git clone https://github.com/YOUR_USERNAME/clipy.git
   cd clipy
   ```
2. Make the installer script executable and run it:
   ```bash
   chmod +x install.sh
   ./install.sh
   ```

The installer script configures `clipy` to run as a **systemd user service**, automatically importing necessary environment variables (`DISPLAY`, `WAYLAND_DISPLAY`, `XAUTHORITY`) to ensure smooth service clipboard access under Wayland sessions.

### Uninstall

To uninstall the systemd service and application shortcuts:

```bash
systemctl --user stop clipy.service
systemctl --user disable clipy.service
rm ~/.config/systemd/user/clipy.service
rm ~/.local/share/applications/clipy.desktop
systemctl --user daemon-reload
```

---

## 🖱️ Mouse & Card Controls

Each clip card includes an inline action bar and right-click support:

* **📋 Copy**: Copy clip and paste into active window.
* **📌 Pin / Unpin**: Toggle pinning (pinned items never expire).
* **🔖 Save**: Save text as permanent labeled snippet.
* **🌐 Open**: Launch URL directly in default web browser.
* **➕ Merge**: Select card for multi-item concatenate merge.
* **🔠 AAA**: Copy text converted to ALL UPPERCASE.
* **🗑️ Delete**: Delete item from history/snippets database.
* **Right-Click**: Opens popup menu with Copy, Pin, Snippet, Open, UPPERCASE, lowercase, Trim, and Delete actions.

---

## ⌨️ Keyboard Shortcuts

### Global (GNOME System Shortcut)

| Shortcut | Action |
|:---|:---|
| `Super+Shift+V` | Toggle Clipy popup window |

### Inside Clipy Popup

| Key | Action |
|:---|:---|
| `↑` / `↓` | Navigate list items / Focus search bar |
| `←` / `→` | Cycle type filter tabs (**ALL**, **URL**, **EMAIL**, **CODE**, **NUMBER**, **IMAGE**) without copying |
| `Ctrl+←` / `Ctrl+→` | Cycle type filter tabs anytime (even while typing in search) |
| `Enter` | **Normal**: Copy selected item & paste into previous window.<br>**Merge Mode**: Open separator dialog and merge selected text clips. |
| `Space` / Click | **Merge Mode**: Toggle selection of highlighted card |
| `O` / `o` | Open highlighted URL clip directly in default browser (`xdg-open`) |
| `P` / `p` | Toggle pinning (pinned items never expire) |
| `S` / `s` | Save highlighted clip permanently as a Snippet with custom label |
| `M` / `m` | Toggle **Merge Mode** (for text clips) |
| `T` / `t` | Toggle between **History** and **Saved Snippets** tabs |
| `E` / `e` | Export complete clipboard history and snippets to a **JSON backup file** |
| `I` / `i` | Import clipboard history and snippets from a **JSON backup file** |
| `/` | Focus search bar |
| `Delete` | Delete selected item from database |
| `Esc` | Close popup without action |

---

## 🔍 Advanced Search Operators

In the search bar (`/`), you can combine text queries with smart filter flags:

* `type:url` — Show only web link clips
* `type:email` — Show only email address clips
* `type:code` — Show code snippets
* `type:image` — Show captured screenshots
* `type:number` — Show numerical clips
* `pinned:true` or `pinned:yes` — Filter pinned items only
* `pinned:false` or `pinned:no` — Filter unpinned items only

**Example search query:**
```text
type:url github
```

---

## ⚙️ Configuration

The default retention period is **4 hours** and history size is capped at **50 items** (oldest unpinned items are automatically dropped).

To customize the retention duration, update the SQLite settings table directly:

```bash
sqlite3 /path/to/project/clipy.db "UPDATE settings SET value = '12' WHERE key = 'retention_hours';"
```

---

## 📄 License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.
