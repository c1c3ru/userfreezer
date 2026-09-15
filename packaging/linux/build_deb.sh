#!/usr/bin/env bash
# Monta deepfreezer_<versao>_all.deb a partir dos arquivos do repo.
# Nao precisa de root para built -- so' pra instalar o .deb resultante.
#
# Uso: packaging/linux/build_deb.sh [diretorio_de_saida]   (default: dist/)
set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SRC_DIR/../.." && pwd)"
VERSION="$(tr -d ' \t\n\r' < "$REPO_ROOT/VERSION")"
OUT_DIR="$(cd "${1:-$REPO_ROOT/dist}" 2>/dev/null && pwd || { mkdir -p "${1:-$REPO_ROOT/dist}" && cd "${1:-$REPO_ROOT/dist}" && pwd; })"
PKG_NAME=deepfreezer

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
chmod 0755 "$STAGE"   # mktemp -d cria com 700; nao queremos isso no root do pacote

install -d -m 0755 "$STAGE/DEBIAN"
install -d -m 0755 "$STAGE/opt/deepfreezer"
install -d -m 0755 "$STAGE/etc/deepfreezer"
install -d -m 0755 "$STAGE/etc/systemd/system"

install -m 0755 "$REPO_ROOT/deepfreezer.py" "$STAGE/opt/deepfreezer/deepfreezer.py"
install -m 0755 "$SRC_DIR/deepfreezerd.py" "$STAGE/opt/deepfreezer/deepfreezerd.py"
install -m 0644 "$REPO_ROOT/packaging/config.example.json" "$STAGE/etc/deepfreezer/config.json"
install -m 0644 "$SRC_DIR/deepfreezer.service" "$STAGE/etc/systemd/system/deepfreezer.service"

install -m 0755 "$SRC_DIR/debian/postinst" "$STAGE/DEBIAN/postinst"
install -m 0755 "$SRC_DIR/debian/prerm" "$STAGE/DEBIAN/prerm"
install -m 0755 "$SRC_DIR/debian/postrm" "$STAGE/DEBIAN/postrm"

cat > "$STAGE/DEBIAN/conffiles" <<EOF
/etc/deepfreezer/config.json
EOF

SIZE_KB=$(du -sk "$STAGE" | cut -f1)
cat > "$STAGE/DEBIAN/control" <<EOF
Package: $PKG_NAME
Version: $VERSION
Section: admin
Priority: optional
Architecture: all
Installed-Size: $SIZE_KB
Depends: python3 (>= 3.6)
Maintainer: userfreezer project <noreply@example.com>
Homepage: https://github.com/c1c3ru/userfreezer
Description: DeepFreezer - application-level directory freeze/thaw
 Congela uma arvore de diretorios e desvia escritas subsequentes para
 uma camada de overlay crash-safe (journal append-only); restaura o
 estado original no proximo boot (servico systemd) ou via
 deepfreezer.py CLI (thaw / thaw --commit). So' Python 3.6+ stdlib,
 sem modulos de kernel ou drivers.
EOF

DEB_PATH="$OUT_DIR/${PKG_NAME}_${VERSION}_all.deb"
dpkg-deb --build --root-owner-group "$STAGE" "$DEB_PATH"
echo "gerado: $DEB_PATH"
