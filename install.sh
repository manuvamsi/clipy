#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

G='\033[0;32m'
B='\033[0;34m'
Y='\033[1;33m'
R='\033[0;31m'
N='\033[0m'

echo -e "${B}══════════════════════════════════════════${N}"
echo -e "${B}     📋  Clipy — Installation Script      ${N}"
echo -e "${B}══════════════════════════════════════════${N}"

# ── 1. Dependencies ──────────────────────────────────────────────
echo -e "\n${B}[1/5] Checking dependencies…${N}"

if ! command -v xsel &>/dev/null; then
    echo -e "${R}  ✗ xsel not found. Install it:  sudo apt install xsel${N}"
    exit 1
fi
echo -e "${G}  ✓ xsel${N}"

if ! python3 -c "import gi" &>/dev/null; then
    echo -e "${R}  ✗ PyGObject (gi) not found. Install it:  sudo apt install python3-gi${N}"
    exit 1
fi
echo -e "${G}  ✓ PyGObject (GTK bindings)${N}"

if command -v xdotool &>/dev/null; then
    echo -e "${G}  ✓ xdotool (paste-and-close enabled)${N}"
else
    echo -e "${Y}  ⚠ xdotool not found — paste-and-close will be disabled.${N}"
    echo -e "${Y}    To enable it later:  sudo apt install xdotool${N}"
fi

# ── 2. Permissions ───────────────────────────────────────────────
echo -e "\n${B}[2/5] Setting permissions…${N}"
chmod +x "${SCRIPT_DIR}/clipy-daemon.py"
chmod +x "${SCRIPT_DIR}/clipy-menu.py"
echo -e "${G}  ✓ Scripts marked executable${N}"

# ── 3. Systemd service ──────────────────────────────────────────
echo -e "\n${B}[3/5] Installing systemd user service…${N}"
SERVICE_DIR="${HOME}/.config/systemd/user"
mkdir -p "$SERVICE_DIR"

cat > "${SERVICE_DIR}/clipy.service" <<EOF
[Unit]
Description=Clipy Clipboard History Daemon
After=graphical-session.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 -u ${SCRIPT_DIR}/clipy-daemon.py
Restart=always
RestartSec=5
Environment=DISPLAY=:0 WAYLAND_DISPLAY=wayland-0

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user import-environment DISPLAY WAYLAND_DISPLAY XAUTHORITY || true
systemctl --user enable clipy.service
systemctl --user restart clipy.service
echo -e "${G}  ✓ clipy.service enabled and started${N}"

# ── 4. Desktop launcher ─────────────────────────────────────────
echo -e "\n${B}[4/5] Installing desktop launcher…${N}"
APP_DIR="${HOME}/.local/share/applications"
mkdir -p "$APP_DIR"
sed "s|Exec=.*|Exec=${SCRIPT_DIR}/clipy-menu.py|" \
    "${SCRIPT_DIR}/clipy.desktop" > "${APP_DIR}/clipy.desktop"
chmod +x "${APP_DIR}/clipy.desktop"
echo -e "${G}  ✓ Clipy added to applications menu${N}"

# ── 5. GNOME keyboard shortcut ──────────────────────────────────
echo -e "\n${B}[5/5] Setting up keyboard shortcut (Super+Shift+V)…${N}"

if command -v gsettings &>/dev/null; then
    KB_PATH="/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings"
    CLIPY_KEY="${KB_PATH}/clipy/"

    current=$(gsettings get org.gnome.settings-daemon.plugins.media-keys custom-keybindings)

    if [[ "$current" != *"${CLIPY_KEY}"* ]]; then
        if [[ "$current" == "@as []" || "$current" == "[]" ]]; then
            new="['${CLIPY_KEY}']"
        else
            new="${current%]*}, '${CLIPY_KEY}']"
        fi
        gsettings set org.gnome.settings-daemon.plugins.media-keys custom-keybindings "$new"
    fi

    gsettings set org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:${CLIPY_KEY} \
        name "Clipy Clipboard History"
    gsettings set org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:${CLIPY_KEY} \
        command "${SCRIPT_DIR}/clipy-menu.py"
    gsettings set org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:${CLIPY_KEY} \
        binding "<Super><Shift>v"

    echo -e "${G}  ✓ Super+Shift+V → Clipy${N}"
else
    echo -e "${Y}  ⚠ gsettings not found. Set the shortcut manually:${N}"
    echo -e "      Command: ${SCRIPT_DIR}/clipy-menu.py"
    echo -e "      Shortcut: Super+Shift+V"
fi

# ── Done ─────────────────────────────────────────────────────────
echo ""
echo -e "${G}══════════════════════════════════════════${N}"
echo -e "${G}  ✓ Clipy installed successfully!${N}"
echo -e "${G}══════════════════════════════════════════${N}"
echo ""
echo -e "  The daemon is running in the background."
echo -e "  Press ${B}Super+Shift+V${N} to open your clipboard history."
echo ""
