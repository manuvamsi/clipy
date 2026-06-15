# 📋 Clipy — Advanced Clipboard History & Snippet Manager for Linux

A lightweight, native, and feature-rich clipboard history manager for Ubuntu and other GNOME-based Linux distributions (supporting both Wayland and X11). Built entirely with Python and GTK 3 (`PyGObject`).

**Zero web frameworks. Zero Electron. Zero bloat.** Just a beautiful, premium, glassmorphic popup that stays out of your way and boosts your productivity.

---

## ✨ Advanced Features

| Feature | Description |
|:---|:---|
| 📋 **Gdk-Native Polling** | Replaces old polling methods with native `Gdk.Clipboard` and event-driven updates. Highly reliable on GNOME/Wayland. |
| 📸 **Image & Screenshot Capture** | Silently monitors clipboard image targets (like printscreens). Compares pixel data via **MD5 hashing** to avoid duplicates, saves screenshots to disk, and displays them as responsive aspect-ratio thumbnails. |
| 📝 **Multi-Select Merge Mode** | Toggle Merge Mode (`M`), select multiple text clips (`Space` or click), and press `Enter` to concatenate them with newline separators. Instantly copies the merged clip to the clipboard, saves it, and highlights it. |
| 🏷️ **Saved Snippets View** | Press `S` to save any clipboard item permanently. Assign a custom label using a native GTK prompt dialog. Toggle between History and Snippets using `T` or clicking tabs. |
| 📊 **Analytics Dashboard** | Live dashboard in the header bar showing today's copies, total history count, saved snippets count, and type distributions. |
| 🎨 **Hex Color Previews** | Automatically detects HEX colors (`#HEX` codes) in text clips and displays a live CSS-rendered color swatch beside the clip. |
| ⏱️ **Automatic GC & Pruning** | Unpinned items automatically expire after 4 hours (configurable). Old image files on disk are automatically cleaned up when items are deleted, pruned, or expired. |
| 🔒 **Privacy-First** | Credit cards, API keys (e.g. `sk-`, `ghp_`, `Bearer`), and sensitive passwords are automatically classified and skipped. Database and screenshots are stored locally. |
| 📋➡️📄 **Paste-and-Close** | Select any item and press Enter to copy it and automatically paste it directly into your previous active application window *(requires `xdotool`)*. |

---

## 📸 How It Works

```
┌────────────────────────────────────┐
│  You copy text/image (Ctrl+C)      │
└──────────────┬─────────────────────┘
               │
               ▼
┌────────────────────────────────────┐
│  clipy-daemon (systemd service)    │
│  • Detects text/image clipboard     │
│  • Performs MD5 pixel hashing      │
│  • Classifies content & saves DB   │
│  • Cleans up image files on prune  │
└────────────────────────────────────┘
               │
               │  Press Super+Shift+V
               ▼
┌────────────────────────────────────┐
│  Premium Glassmorphic GTK Popup    │
│  • View, filter, and search        │
│  • Toggle Merge Mode (M)           │
│  • Toggle Snippets Tab (T)         │
│  • Enter twice to copy and paste   │
└────────────────────────────────────┘
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

The installer script configures `clipy` to run as a **systemd user service**, automatically importing the necessary environment variables (`DISPLAY`, `WAYLAND_DISPLAY`, `XAUTHORITY`) to ensure smooth systemd service clipboard access under Wayland sessions.

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

## ⌨️ Keyboard Shortcuts

### Global (GNOME System Shortcut)

| Shortcut | Action |
|:---|:---|
| `Super+Shift+V` | Toggle Clipy popup |

### Inside Clipy Popup

| Key | Action |
|:---|:---|
| `↑` / `↓` | Navigate list items / Focus search |
| `Enter` | **Normal**: Copy & paste selected item to previous window. <br>**Merge Mode**: Concatenate selected items and focus the new clip. |
| `Space` / Click | **Merge Mode**: Toggle selection of the highlighted card. |
| `P` / `p` | Toggle pinning of history clips (pinned items never expire). |
| `S` / `s` | Save focused clip permanently as a Snippet with a custom label. |
| `M` / `m` | Toggle **Merge Mode** (for text clips). |
| `T` / `t` | Toggle between **History** and **Saved Snippets** tabs. |
| `/` | Focus search bar. |
| `Delete` | Remove the selected item from history/snippets. |
| `Esc` | Close popup without action. |

---

## ⚙️ Configuration

The default retention period is **4 hours** and the history size is capped at **50 items** (oldest unpinned items are automatically dropped).

To customize the retention duration, update the SQLite settings table directly:

```bash
sqlite3 ~/.config/clipy/clipy.db "UPDATE settings SET value = '12' WHERE key = 'retention_hours';"
```

---

## 👨‍💻 Play & Contribute (Developer Invite)

Welcome! If you are a developer looking to build on top of Clipy or customize it for your workflow, feel free to fork this project, experiment with the codebase, and submit Pull Requests! 

Here are a few exciting features/ideas on our roadmap that you can build and add to the system:
- **📊 Graphical Statistics**: Integrate a visual chart dashboard showing clipboard analytics over the last 30 days.
- **☁️ Cloud Sync & Backups**: Add secure synchronization for saved snippets across devices (e.g. via Nextcloud or GitHub Gists).
- **⚙️ Hotkey Configuration UI**: Create an interactive GUI dialog to easily change the default database paths, hotkeys, and retention limits.
- **🔍 Advanced Search Operators**: Add support for regex searches, sorting options, and tags-based filters.
- **🖼️ Snippet Categories**: Group saved snippets into folders or categories (e.g. `Code Templates`, `Frequently Used Emails`, `URLs`).

---

## 📄 License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.
