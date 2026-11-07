"""Deterministic PII scrubbing for logistics documents and production logs.

    python -m scripts.scrub --in raw.txt --out clean.txt
    python -m scripts.scrub --check clean.txt

This is a first pass, not a guarantee. Always review scrubbed data before it
enters data/. Never commit raw customer data.
"""

from __future__ import annotations

import argparse
import re
import sys

from scripts.common import atomic_write

RULES = (
    ("email", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
    ("card", re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")),
    ("iban", re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b")),
    ("address", re.compile(r"(?im)^(?:address|pickup address|delivery address)\s*:.*$")),
    ("contact", re.compile(r"(?im)^(?:contact|attention)\s*:.*$")),
)

PHONE_RE = re.compile(r"(?<!\d)(?:\+?\d{1,3}[\s.-]?)?(?:\(?\d{2,4}\)?[\s.-]?){2,4}\d{2,4}(?!\d)")
DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?)?\b")


def _redact_phone(match: re.Match) -> str:
    value = match.group(0).strip()
    if DATE_RE.fullmatch(value):
        return match.group(0)
    digits = re.sub(r"\D", "", value)
    if len(digits) < 7:
        return match.group(0)
    return "[REDACTED:phone]"


def scrub(text: str) -> tuple[str, dict[str, int]]:
    counts: dict[str, int] = {}
    text, n = PHONE_RE.subn(_redact_phone, text)
    replaced = sum(1 for _ in re.finditer(r"\[REDACTED:phone\]", text))
    if replaced:
        counts["phone"] = replaced
    for name, pattern in RULES:
        text, n = pattern.subn(f"[REDACTED:{name}]", text)
        if n:
            counts[name] = n
    return text, counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--in", dest="infile", required=True)
    parser.add_argument("--out", dest="outfile")
    parser.add_argument("--check", action="store_true", help="report findings and exit 1 if any")
    args = parser.parse_args(argv)

    text = open(args.infile, encoding="utf-8").read()
    cleaned, counts = scrub(text)

    if args.check:
        if counts:
            print(f"{args.infile}: {counts}")
            return 1
        print(f"{args.infile}: clean")
        return 0

    if not args.outfile:
        parser.error("--out is required unless --check is used")
    atomic_write(args.outfile, cleaned)
    print(f"wrote {args.outfile} (redactions: {counts or 'none'})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
