#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Map Debian-compatible release-candidate versions to GitHub SemVer tags.

0.2.0~rc1 sorts BEFORE 0.2.0 under dpkg and prevents an RC .deb from
blocking a later stable upgrade. GitHub's human-facing tag remains
v0.2.0-rc.1. Do not conflate release candidates with stable validation.
Python 3.8+; standard library only.
"""
import argparse
import re

_STABLE = re.compile(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)\Z")
_RC = re.compile(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)~rc([1-9]\d*)\Z")


def get_channel(version):
    if not isinstance(version, str) or len(version) > 80:
        raise ValueError("versao de release invalida")
    stable = _STABLE.fullmatch(version)
    if stable is not None:
        return {"tag": "v" + version, "prerelease": "false",
                "title": "v" + version}
    candidate = _RC.fullmatch(version)
    if candidate is not None:
        tag = "v%s.%s.%s-rc.%s" % candidate.groups()
        return {"tag": tag, "prerelease": "true",
                "title": tag + " — Prévia para teste humano (não certificada)"}
    raise ValueError("versao nao segue semver ou versao Debian ~rcN")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", required=True)
    ap.add_argument("--field", required=True, choices=("tag", "prerelease", "title"))
    args = ap.parse_args(argv)
    print(get_channel(args.version)[args.field])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
