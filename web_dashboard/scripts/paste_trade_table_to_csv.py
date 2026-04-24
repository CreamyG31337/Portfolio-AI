#!/usr/bin/env python3
"""
Parse a pasted Trade Entry–style block (Date / Action / Ticker / Full Name / Shares / Price / Total / Reason)
into CSV columns: ticker, date, reason.

Usage:
  python paste_trade_table_to_csv.py reasons_paste.txt -o reasons.csv
  python paste_trade_table_to_csv.py -o reasons.csv --excel < reasons_paste.txt
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

DATE_RE = re.compile(
    r"^\d{1,2}/\d{1,2}/\d{4}\s+\d{1,2}:\d{2}\s*(?:AM|PM)\s*$",
    re.IGNORECASE,
)


def parse_lines(lines: list[str]) -> list[tuple[str, str, str]]:
    lines = [ln.rstrip("\n\r") for ln in lines]
    i = 0
    n = len(lines)
    while i < n and not DATE_RE.match(lines[i].strip()):
        i += 1

    out: list[tuple[str, str, str]] = []
    while i < n:
        line = lines[i].strip()
        if not DATE_RE.match(line):
            i += 1
            continue

        date_str = line
        i += 1
        if i >= n:
            break
        i += 1  # action
        if i >= n:
            break
        ticker = lines[i].strip()
        i += 1
        if i >= n:
            break
        i += 1  # full name
        if i >= n:
            break
        i += 1  # shares
        if i >= n:
            break
        i += 1  # price
        if i >= n:
            break
        i += 1  # total
        reason_parts: list[str] = []
        while i < n:
            nxt = lines[i].strip()
            if DATE_RE.match(nxt):
                break
            if nxt:
                reason_parts.append(nxt)
            i += 1
        reason = " ".join(reason_parts).strip()
        out.append((ticker, date_str, reason))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Paste-style trade table → CSV (ticker, date, reason).")
    ap.add_argument(
        "input",
        nargs="?",
        type=Path,
        help="Input .txt file (default: stdin)",
    )
    ap.add_argument("-o", "--output", type=Path, help="Output .csv path (default: stdout)")
    ap.add_argument("--excel", action="store_true", help="UTF-8-SIG for Excel (requires -o)")
    args = ap.parse_args()

    if args.excel and not args.output:
        print("--excel requires -o (output path)", file=sys.stderr)
        return 2

    if args.input is None:
        text = sys.stdin.read()
        lines = text.splitlines(keepends=False)
    else:
        lines = args.input.read_text(encoding="utf-8").splitlines()

    rows = parse_lines(lines)
    if not rows:
        print("No rows parsed. Ensure lines start with dates like 02/12/2026 04:05 PM", file=sys.stderr)
        return 1

    out_enc = "utf-8-sig" if args.excel else "utf-8"
    if args.output:
        f = args.output.open("w", encoding=out_enc, newline="")
    else:
        f = sys.stdout

    try:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["ticker", "date", "reason"])
        w.writerows(rows)
    finally:
        if args.output:
            f.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
