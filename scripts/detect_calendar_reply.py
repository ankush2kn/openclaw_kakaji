#!/usr/bin/env python3
"""Detect whether a Gmail thread contains a calendar *response* (REPLY)
*for events organized by botbhargava@gmail.com*.

We want to ignore RSVP responses like:
- Subject: Accepted:/Declined:/Tentative:  (heuristic only)
- text/calendar parts with METHOD:REPLY + ORGANIZER matching botbhargava@gmail.com

Input: Gmail thread JSON on stdin (from `gog gmail thread get --full --json`).
Output: 'yes' or 'no' on stdout.

Rule: return 'yes' ONLY when we can confirm the calendar part is a reply
(METHOD:REPLY) AND the organizer email is botbhargava@gmail.com.

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


ORGANIZER_EMAIL = "botbhargava@gmail.com"


def _extract_organizer_email(ics_text: str) -> str:
    # Matches lines like:
    # ORGANIZER;CN=Bot:mailto:botbhargava@gmail.com
    # ORGANIZER:mailto:botbhargava@gmail.com
    m = re.search(r"^ORGANIZER[^:\n\r]*:mailto:([^\s\n\r]+)", ics_text, flags=re.I | re.M)
    if not m:
        return ""
    return (m.group(1) or "").strip().lower()


def _has_method_reply(ics_text: str) -> bool:
    return re.search(r"\bMETHOD:REPLY\b", ics_text, re.I) is not None


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

        # Heuristic subject check is NOT sufficient by itself.
        # Only treat as a calendar reply if we also find a text/calendar part with METHOD:REPLY
        # organized by botbhargava@gmail.com.
        subject_looks_like_reply = bool(subject and subj_re.search(subject))

        # Look for text/calendar parts and METHOD:REPLY either in headers or body
        for part in _walk_parts(payload):
            mt = (part.get("mimeType") or "").lower()
            ph = part.get("headers") or []
            ctype = _get_header(ph, "content-type").lower()

            if "text/calendar" in mt or "text/calendar" in ctype:
                body_data = (part.get("body") or {}).get("data")
                txt = _b64url_decode(body_data) if body_data else ""

                # Determine method reply (from header param or body)
                header_has_reply = "method=reply" in ctype.replace(" ", "")
                body_has_reply = _has_method_reply(txt)
                if not (header_has_reply or body_has_reply):
                    continue

                organizer = _extract_organizer_email(txt)
                if organizer == ORGANIZER_EMAIL:
                    print("yes")
                    return 0

    # If it only *looked* like a reply from the subject, but we didn't confirm via ICS,
    # be conservative and do NOT classify it as a reply.
    print("no")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
