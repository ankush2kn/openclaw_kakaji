#!/usr/bin/env python3
"""Resolve a contact token (name or email) to an email using CONTACTS.md.

Usage:
  resolve_contact.py <contacts_md_path> <token>

Rules:
- If token contains '@': treat as email and print it lowercased.
- Else: treat as a name; look up exact case-insensitive match in CONTACTS.md lines of form:
    Name -> email@address.com
  Print the mapped email lowercased.
- If not found: print nothing and exit 0.

No LLM usage. Deterministic.
"""

import re
import sys


def main():
    if len(sys.argv) != 3:
        return
    path = sys.argv[1]
    token = (sys.argv[2] or "").strip()
    if not token:
        return

    token_lc = token.lower()

    # Trim surrounding punctuation that often appears in natural text (e.g. "Shuchi." or "<Shuchi>")
    token_lc = re.sub(r"^[^a-z0-9@]+|[^a-z0-9@]+$", "", token_lc)

    if "@" in token_lc:
        print(token_lc)
        return

    name = token_lc

    try:
        lines = open(path, "r", encoding="utf-8").read().splitlines()
    except FileNotFoundError:
        return

    for ln in lines:
        ln = ln.strip()
        if not ln or ln.startswith("#") or ln.startswith("-"):
            continue
        # Allow trailing comments after the email (e.g. "Name -> email (default)")
        m = re.match(r"^(.*?)\s*->\s*([^\s]+)", ln)
        if not m:
            continue
        n = m.group(1).strip().lower()
        e = m.group(2).strip().lower()
        if n == name:
            print(e)
            return


if __name__ == "__main__":
    main()
