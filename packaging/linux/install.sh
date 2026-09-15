#!/usr/bin/env bash
# Instala o DeepFreezer como servico systemd (Linux). Rodar como root.
#
# Uso: sudo ./install.sh
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "erro: rode como root (sudo $0)" >&2
  exit 1
fi

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SRC_DIR/../.." && pwd)"
INSTALL_DIR=/opt/deepfreezer
CONFIG_DIR=/etc/deepfreezer
UNIT_PATH=/etc/systemd/system/deepfreezer.service

install -d -m 0755 "$INSTALL_DIR"
install -m 0755 "$REPO_ROOT/deepfreezer.py" "$INSTALL_DIR/deepfreezer.py"
install -m 0755 "$SRC_DIR/deepfreezerd.py" "$INSTALL_DIR/deepfreezerd.py"

install -d -m 0700 "$CONFIG_DIR"
if [ ! -f "$CONFIG_DIR/config.json" ]; then
  install -m 0600 "$REPO_ROOT/packaging/config.example.json" "$CONFIG_DIR/config.json"
  echo "criado $CONFIG_DIR/config.json a partir do exemplo -- edite 'targets' antes de habilitar o servico"
fi
chown -R root:root "$CONFIG_DIR"

install -m 0644 "$SRC_DIR/deepfreezer.service" "$UNIT_PATH"

systemctl daemon-reload
systemctl enable deepfreezer.service

echo "instalado. revise $CONFIG_DIR/config.json e rode: systemctl start deepfreezer"
