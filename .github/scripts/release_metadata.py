#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Manifesto reproducivel de checksums e SPDX 2.3 nivel-artefato.

Nao substitui um inventario transitorio de dependencias/supply-chain.
Requer apenas stdlib Python 3.8+.
"""
import argparse
import datetime
import hashlib
import json
import os


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def make_metadata(root, out, version):
    files = []
    for directory, _dirs, filenames in os.walk(root):
        for name in filenames:
            if name.lower().endswith((".deb", ".exe", ".zip")):
                files.append(os.path.join(directory, name))
    files.sort(key=lambda x: os.path.basename(x))
    names = [os.path.basename(p) for p in files]
    expected = [
        "deepfreezer_%s_all.deb" % version,
        "deepfreezer_service_windows-10-11.exe",
        "deepfreezer_service_windows-7-8.exe",
        "deepfreezer-windows-service-scripts.zip",
        "deepfreezer-windows-os-level.zip",
    ]
    if sorted(names) != sorted(expected):
        raise ValueError("artifacts divergentes. Esperados=%r; encontrados=%r" %
                         (expected, names))
    os.makedirs(out, exist_ok=True)
    hashes = [(os.path.basename(p), sha256(p)) for p in files]
    with open(os.path.join(out, "SHA256SUMS"), "w", encoding="utf-8") as f:
        for name, digest in hashes:
            f.write("%s  %s\n" % (digest, name))
    packages = []
    relationships = []
    for i, (name, digest) in enumerate(hashes):
        pid = "SPDXRef-ReleaseArtifact-%d" % (i + 1)
        packages.append({
            "name": name, "SPDXID": pid, "versionInfo": version,
            "downloadLocation": "NOASSERTION", "filesAnalyzed": False,
            "licenseConcluded": "NOASSERTION",
            "licenseDeclared": "NOASSERTION",
            "copyrightText": "NOASSERTION",
            "checksums": [{"algorithm": "SHA256", "checksumValue": digest}],
        })
        relationships.append({
            "spdxElementId": "SPDXRef-DOCUMENT",
            "relatedSpdxElement": pid,
            "relationshipType": "DESCRIBES",
        })
    sbom = {
        "spdxVersion": "SPDX-2.3", "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": "DeepFreezer release artifacts %s" % version,
        "documentNamespace": "https://github.com/c1c3ru/userfreezer/spdx/%s" % version,
        "creationInfo": {
            "created": datetime.datetime.now(datetime.timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"),
            "creators": ["Tool: userfreezer-release-metadata"],
        },
        "packages": packages, "relationships": relationships,
        "annotations": [],
    }
    with open(os.path.join(out, "release.spdx.json"), "w", encoding="utf-8") as f:
        json.dump(sbom, f, indent=2, sort_keys=True)
        f.write("\n")
    return hashes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", required=True)
    ap.add_argument("--artifacts", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    for name, digest in make_metadata(args.artifacts, args.out, args.version):
        print(digest, name)


if __name__ == "__main__":
    main()
