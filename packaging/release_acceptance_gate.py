#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fail-closed DOCUMENTARY acceptance gate for publishing v0.2.0.

Only accepts reviewer-curated issue-comment evidence links recorded in the
repository. This is NOT cryptographic verification of a VM, signatures, UAC
or rollback. Publishing still requires human review of the linked evidence
and protected release permissions. Other versions are unaffected.
"""
import argparse
import json
import re
import sys

REQUIRED = ("63", "49", "54", "56")
MAX_RECORD_BYTES = 32 * 1024
_REVIEWER = re.compile(r"[A-Za-z0-9-]{1,39}\Z")


def _comment_url(value, issue):
    if not isinstance(value, str):
        return False
    pattern = (r"https://github\.com/c1c3ru/userfreezer/issues/" +
               re.escape(issue) + r"#issuecomment-[1-9][0-9]*\Z")
    return re.fullmatch(pattern, value) is not None


def validate_v020_acceptance(record):
    """Validate the exact evidence manifest; returns issue IDs still blocked."""
    if not isinstance(record, dict) or set(record) != {
            "schema", "version", "issues", "review"}:
        raise ValueError("manifesto de aceite invalido")
    if (type(record["schema"]) is not int or record["schema"] != 1 or
            record["version"] != "0.2.0"):
        raise ValueError("versao/schema de aceite divergente")
    issues = record["issues"]
    if not isinstance(issues, dict) or set(issues) != set(REQUIRED):
        raise ValueError("issues obrigatorias #63 #49 #54 #56 ausentes")
    blocked = []
    for issue in REQUIRED:
        value = issues[issue]
        if not isinstance(value, dict) or set(value) != {"state", "evidence"}:
            raise ValueError("estado da issue #%s invalido" % issue)
        state = value["state"]
        evidence = value["evidence"]
        if state not in ("pending", "verified"):
            raise ValueError("estado de evidencias nao permitido #%s" % issue)
        if (not isinstance(evidence, list) or len(evidence) > 12 or
                len(evidence) != len(set(str(v) for v in evidence))):
            raise ValueError("lista de evidencias invalida #%s" % issue)
        if not all(_comment_url(v, issue) for v in evidence):
            raise ValueError("URLs de evidencias nao correspondem a issue #%s" % issue)
        if state != "verified" or not evidence:
            blocked.append(issue)
    review = record["review"]
    if not isinstance(review, dict) or set(review) != {
            "approved", "reviewer", "approval_url"}:
        raise ValueError("revisao de release invalida")
    if type(review["approved"]) is not bool:
        raise ValueError("aprovacao deve ser boolean")
    if review["approved"]:
        if (not isinstance(review["reviewer"], str) or
                _REVIEWER.fullmatch(review["reviewer"]) is None or
                not any(_comment_url(review["approval_url"], issue)
                        for issue in REQUIRED)):
            raise ValueError("aprovacao/revisor de release sem referencia")
    elif review["reviewer"] is not None or review["approval_url"] is not None:
        raise ValueError("revisao pendente nao pode simular aprovacao")
    if not review["approved"]:
        blocked.append("review")
    return blocked


def read_manifest(path):
    with open(path, "rb") as stream:
        raw = stream.read(MAX_RECORD_BYTES + 1)
    if not raw or len(raw) > MAX_RECORD_BYTES:
        raise ValueError("manifesto de aceite ausente ou extenso")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("campo JSON duplicado")
            result[key] = value
        return result
    try:
        data = json.loads(raw.decode("utf-8"), object_pairs_hook=unique)
    except (UnicodeError, ValueError) as exc:
        raise ValueError("manifesto JSON invalido") from exc
    return data


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--record", required=True)
    args = parser.parse_args(argv)
    if args.version != "0.2.0":
        print("Acceptance gate #63/#49/#54/#56 not applicable to %s" %
              args.version)
        return 0
    try:
        pending = validate_v020_acceptance(read_manifest(args.record))
    except (OSError, ValueError, TypeError) as exc:
        print("RELEASE BLOCKED: invalid acceptance record: %s" % exc,
              file=sys.stderr)
        return 2
    if pending:
        print("RELEASE BLOCKED: pending real VM/UAC approval evidence: %s" %
              ", ".join(pending), file=sys.stderr)
        return 2
    print("Documentary v0.2.0 acceptance recorded. Manual proof review "
          "and GitHub permissions remain mandatory.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
