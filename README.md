# 📋 Clipy — Clipboard History Manager for Linux

A lightweight, native clipboard history manager for Ubuntu and other GNOME-based Linux distributions. Inspired by Windows' `Win+V` clipboard and Android's Gboard clipboard — built entirely with Python and GTK.

**Zero browser. Zero Electron. Zero bloat.** Just a fast, native popup that lives in your system tray.

---

## ✨ Features

| Feature | Description |
|---------|-------------|
| 📋 **Auto-capture** | Silently monitors your clipboard in the background. Every `Ctrl+C` is saved automatically. |
| 🔍 **Instant search** | Type to filter through your clipboard history in real time. |
| ⌨️ **Keyboard-first** | Full keyboard navigation — arrows, Enter to paste, P to pin, Del to remove, Esc to close. |
| 📌 **Pin important clips** | Pinned items never expire and stay at the top of your history. |
| ⏱️ **Auto-expiry** | Unpinned clips are automatically cleared after 4 hours (configurable). |
| 🏷️ **Content type badges** | Each clip is tagged as 🔗 URL, 📧 Email, 💻 Code, 🔢 Number, or 📝 Text. |
| 🔒 **Privacy-first** | Passwords, API tokens, and credit card numbers are automatically detected and **never stored**. |
| 📋➡️📄 **Paste-and-close** | Select an item → it's pasted directly into your previous app. Just like Windows. *(requires `xdotool`)* |
| 🪶 **Ultra-lightweight** | ~10 MB RAM. No browser, no Electron, no web server. Pure Python + GTK. |
| 🚀 **Auto-start** | Installs as a systemd user service. Starts on login, restarts on crash. |

---

## 📸 How It Works

```
┌────────────────────────────────────┐
│  You copy text (Ctrl+C) anywhere  │
└──────────────┬─────────────────────┘
               │
               ▼
┌────────────────────────────────────┐
│  clipy-daemon (background)        │
│  • Detects new clipboard content  │
│  • Filters sensitive data         │
│  • Classifies content type        │
│  • Saves to local SQLite DB       │
└────────────────────────────────────┘
               │
               │  Press Super+Shift+V
               ▼
┌────────────────────────────────────┐
│  Native GTK popup appears         │
│  • Search your history            │
│  • Navigate with arrow keys       │
│  • Press Enter → auto-paste       │
└────────────────────────────────────┘
```

---

## 🚀 Installation

### Prerequisites

- **Ubuntu 22.04+** (or any GNOME-based Linux distro)
- **Python 3.10+** (pre-installed on Ubuntu)
- **PyGObject** (pre-installed on Ubuntu)
- **xsel** — clipboard interface

```bash
# Install required dependency
sudo apt install xsel

# Optional: enables paste-and-close (auto-paste into previous window)
sudo apt install xdotool
```

### Install Clipy

```bash
git clone https://github.com/YOUR_USERNAME/clipy.git
cd clipy
chmod +x install.sh
./install.sh
```

That's it. The daemon starts immediately and will auto-start on every login.

### Uninstall

```bash
systemctl --user stop clipy.service
systemctl --user disable clipy.service
rm ~/.config/systemd/user/clipy.service
rm ~/.local/share/applications/clipy.desktop
systemctl --user daemon-reload
```

---

## ⌨️ Keyboard Shortcuts

### Global (GNOME)

| Shortcut | Action |
|----------|--------|
| `Super+Shift+V` | Open Clipy popup |

### Inside Clipy

| Key | Action |
|-----|--------|
| `↑` / `↓` | Navigate between clips |
| `Enter` | Copy selected clip & paste into previous window |
| `P` | Pin / unpin the selected clip |
| `Delete` | Remove the selected clip |
| `/` | Focus the search box |
| `Esc` | Close without action |

---

## ⚙️ Configuration

The default retention period is **4 hours**. To change it, update the database directly:

```bash
sqlite3 ~/path/to/clipy/clipy.db "UPDATE settings SET value = '12' WHERE key = 'retention_hours';"
```

The maximum number of stored items is **50** (oldest unpinned items are dropped when the limit is reached).

---

## 🔒 Privacy & Security

Clipy is designed with privacy in mind:

- **All data is stored locally** in a SQLite file — nothing is sent over the network.
- **Sensitive content is never stored**: credit card numbers, API tokens (`sk-`, `ghp_`, `Bearer`), and password patterns are automatically detected and silently skipped.
- **Auto-expiry** ensures old clips don't linger.
- **Pinned items** are explicitly opted-in by the user.

---

## 🛠️ Tech Stack

| Component | Technology |
|-----------|-----------|
| Daemon | Python 3 (stdlib only) |
| Database | SQLite 3 |
| GUI | GTK 3 via PyGObject |
| Styling | GTK CSS (glassmorphic dark theme) |
| Clipboard | `xsel` (X11/Xwayland) |
| Auto-paste | `xdotool` (optional) |
| Service | systemd user service |

---

## 🤝 Contributing

Contributions are welcome! Feel free to open issues or submit pull requests.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

---

## 📄 License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.

---

## 🙏 Acknowledgments

- Inspired by **Windows Win+V** clipboard history and **Android Gboard** clipboard
- Built for the Ubuntu community 🐧
