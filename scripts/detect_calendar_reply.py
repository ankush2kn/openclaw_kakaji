#!/usr/bin/env python3
"""Detect whether a Gmail thread contains a calendar *response* (REPLY).

We want to ignore RSVP responses like:
- Subject: Accepted:/Declined:/Tentative:
- text/calendar parts with METHOD:REPLY

Input: Gmail thread JSON on stdin (from `gog gmail thread get --full --json`).
Output: 'yes' or 'no' on stdout.

This is best-effort but aims to be conservative: if it looks like a reply,
return 'yes'.
"""

import base64
import json
import re
import sys


def _b64url_decode(data: str) -> str:
    if not data:
        return ""
    data = data.replace("-", "+").replace("_", "/")
    pad = "=" * (-len(data) % 4)
    try:
        return base64.b64decode(data + pad).decode("utf-8", errors="replace")
    except Exception:
        return ""


def _walk_parts(part):
    if not part:
        return
    yield part
    for p in part.get("parts") or []:
        yield from _walk_parts(p)


def _get_header(headers, name: str) -> str:
    name = name.lower()
    for h in headers or []:
        if (h.get("name") or "").lower() == name:
            return h.get("value") or ""
    return ""


def main() -> int:
    try:
        thread_json = json.load(sys.stdin)
    except Exception:
        print("no")
        return 0

    thread = thread_json.get("thread") or thread_json
    msgs = thread.get("messages") or []

    subj_re = re.compile(r"^(accepted|declined|tentative|updated):\s*", re.I)

    for m in msgs:
        payload = m.get("payload") or {}
        headers = payload.get("headers") or []
        subject = _get_header(headers, "subject").strip()
        if subject and subj_re.search(subject):
            print("yes")
            return 0

        # Look for text/calendar parts and METHOD:REPLY either in headers or body
        for part in _walk_parts(payload):
            mt = (part.get("mimeType") or "").lower()
            ph = part.get("headers") or []
            ctype = _get_header(ph, "content-type").lower()

            if "text/calendar" in mt or "text/calendar" in ctype:
                if "method=reply" in ctype.replace(" ", ""):
                    print("yes")
                    return 0

                body_data = (part.get("body") or {}).get("data")
                txt = _b64url_decode(body_data) if body_data else ""
                # Some calendar parts are not base64 in body.data, but if present, check.
                if re.search(r"\bMETHOD:REPLY\b", txt, re.I):
                    print("yes")
                    return 0

    print("no")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
