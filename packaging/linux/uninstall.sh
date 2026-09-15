#!/usr/bin/env bash
# Remove o servico systemd do DeepFreezer. Rodar como root.
#
# Por padrao preserva /etc/deepfreezer (config) e qualquer overlay
# .dfreezer existente sob os alvos configurados. Passe --purge para
# tambem apagar a configuracao.
#
# Uso: sudo ./uninstall.sh [--purge]
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "erro: rode como root (sudo $0)" >&2
  exit 1
fi

systemctl disable --now deepfreezer.service 2>/dev/null || true
rm -f /etc/systemd/system/deepfreezer.service
systemctl daemon-reload
rm -rf /opt/deepfreezer

if [ "${1:-}" = "--purge" ]; then
  rm -rf /etc/deepfreezer
  echo "removido, incluindo configuracao (/etc/deepfreezer)"
else
  echo "removido. configuracao preservada em /etc/deepfreezer (use --purge para apagar)"
fi
