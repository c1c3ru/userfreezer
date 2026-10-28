#!/usr/bin/env bash
# Integração real Linux: apenas diretório descartável /srv, nunca rootfs.
# Depende de runner/VM Linux com sudo + CAP_SYS_ADMIN + OverlayFS.
set -euo pipefail

sudo mkdir -p /srv
TARGET="$(sudo mktemp -d /srv/deepfreezer-ci-oslevel-XXXXXXXX)"
TOKEN="$(python3 -c 'import hashlib,sys; print(hashlib.sha256(sys.argv[1].encode("utf-8")).hexdigest()[:20])' "$TARGET")"
STAGING="/run/deepfreezer-overlayfs/$TOKEN"

cleanup() {
  set +e
  if mountpoint -q "$TARGET"; then sudo umount "$TARGET"; fi
  if mountpoint -q "$STAGING"; then sudo umount "$STAGING"; fi
  case "$TARGET" in /srv/deepfreezer-ci-oslevel-*) sudo rm -rf -- "$TARGET";; esac
  case "$STAGING" in /run/deepfreezer-overlayfs/*) sudo rm -rf -- "$STAGING";; esac
}
trap cleanup EXIT

printf 'baseline\n' | sudo tee "$TARGET/baseline.txt" >/dev/null
sudo python3 - "$TARGET" <<'PY'
import importlib.util, sys
spec = importlib.util.spec_from_file_location(
    "overlayfs_session", "packaging/linux/overlayfs_session.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.validate_stable_boot_target(sys.argv[1])
PY
python3 packaging/linux/overlayfs_session.py --target "$TARGET" --enable --dry-run
sudo python3 packaging/linux/overlayfs_session.py --target "$TARGET" --enable \
  --size-mb 64 --i-accept-volatile-protection

mountpoint -q "$TARGET" || { echo "overlay nao montado"; exit 1; }
test "$(findmnt -n -o FSTYPE --mountpoint "$TARGET")" = overlay
test "$(python3 packaging/linux/overlayfs_session.py --target "$TARGET" --status | python3 -c 'import json,sys; print(json.load(sys.stdin)["state"])')" = active
python3 - "$TARGET" <<'PY'
import json
import sys
from os_level_status import probe_target
observed = probe_target(sys.argv[1])
assert observed["state"] == "active", observed
assert observed["scope"] == "os-level-directory", observed
assert not observed["reboot_verified"], observed
print("OS-level snapshot ativo por kernel:", json.dumps(observed))
PY

# Gravador EXTERNO: shell/tee, sem passar pela API DeepFreezer.
printf 'externa\n' | sudo tee "$TARGET/outside.txt" >/dev/null
printf 'alterado\n' | sudo tee "$TARGET/baseline.txt" >/dev/null
test "$(sudo cat "$TARGET/outside.txt")" = externa
test "$(sudo cat "$TARGET/baseline.txt")" = alterado

sudo umount "$TARGET"
python3 - "$TARGET" <<'PY'
import sys
from os_level_status import probe_target
observed = probe_target(sys.argv[1])
assert observed["state"] == "inactive", observed
PY
test ! -e "$TARGET/outside.txt"
test "$(sudo cat "$TARGET/baseline.txt")" = baseline
echo "OK: writes externos foram descartados APOS unmount do OverlayFS."
echo "NAO comprova persistencia apos reboot, initramfs ou protecao da raiz."
