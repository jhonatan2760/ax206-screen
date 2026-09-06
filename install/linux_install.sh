#!/usr/bin/env bash
# Instala no Linux: regra udev + quirk do usb-storage (pede sudo) e o servico
# de usuario do watcher (systemd --user), reiniciado sozinho se cair.
#
# Antes: pip install pyusb pillow psutil pynvml
#        apt install x11-utils libusb-1.0-0   (xprop/xwininfo p/ janela em foco)
set -euo pipefail

DIR="$(cd "$(dirname "$0")/.." && pwd)"
PY="${PYTHON:-$(command -v python3)}"

echo "== pasta: $DIR"
echo "== python: $PY"
"$PY" -c "import usb, PIL, psutil" || { echo "faltam dependencias python (pyusb pillow psutil)"; exit 1; }

echo "== udev + usb-storage quirk (sudo)"
sudo install -m 644 "$DIR/install/99-ax206.rules" /etc/udev/rules.d/99-ax206.rules
sudo install -m 644 "$DIR/install/ax206-usb-storage.conf" /etc/modprobe.d/ax206-usb-storage.conf
sudo udevadm control --reload-rules
sudo udevadm trigger
if [ -w /sys/module/usb_storage/parameters/quirks ] || [ -e /sys/module/usb_storage/parameters/quirks ]; then
    echo 1908:0102:i | sudo tee /sys/module/usb_storage/parameters/quirks >/dev/null || true
fi

echo "== servico de usuario"
mkdir -p "$HOME/.config/systemd/user"
sed -e "s|@DIR@|$DIR|g" -e "s|@PY@|$PY|g" \
    "$DIR/install/ax206-watcher.service" > "$HOME/.config/systemd/user/ax206-watcher.service"
systemctl --user daemon-reload
systemctl --user enable --now ax206-watcher.service

echo
echo "ok. Comandos uteis:"
echo "  systemctl --user status ax206-watcher"
echo "  $PY -m watcher --status        (na pasta $DIR)"
echo "  tail -f $DIR/watcher.log"
echo "Se a tela ja estava conectada quando rodou isto, desconecte e reconecte o cabo uma vez."
echo "Para o servico subir sem login grafico ativo: loginctl enable-linger $USER"
