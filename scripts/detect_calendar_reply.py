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


def _has_rsvp_partstat(ics_text: str) -> bool:
    """Some clients send RSVP updates that don't carry METHOD:REPLY reliably.

    We treat an ICS as a response if it contains an attendee PARTSTAT that
    indicates an RSVP outcome.
    """

    return re.search(r"\bPARTSTAT=(ACCEPTED|DECLINED|TENTATIVE)\b", ics_text, re.I) is not None


def main() -> int:
    try:
        thread_json = json.load(sys.stdin)
    except Exception:
        print("no")
        return 0

    thread = thread_json.get("thread") or thread_json
    msgs = thread.get("messages") or []

    subj_re = re.compile(r"^(accepted|declined|tentative|updated):\s*", re.I)
    subj_mentions_organizer_re = re.compile(r"\(" + re.escape(ORGANIZER_EMAIL) + r"\)", re.I)

    for m in msgs:
        payload = m.get("payload") or {}
        headers = payload.get("headers") or []
        subject = _get_header(headers, "subject").strip()

        # Heuristic subject check is NOT sufficient by itself.
        # Only treat as a calendar reply if we also find a text/calendar part with METHOD:REPLY
        # organized by botbhargava@gmail.com.
        subject_looks_like_reply = bool(subject and subj_re.search(subject))
        subject_mentions_organizer = bool(subject and subj_mentions_organizer_re.search(subject))

        # Look for text/calendar parts and METHOD:REPLY either in headers or body
        for part in _walk_parts(payload):
            mt = (part.get("mimeType") or "").lower()
            ph = part.get("headers") or []
            ctype = _get_header(ph, "content-type").lower()

            if "text/calendar" in mt or "text/calendar" in ctype:
                body_data = (part.get("body") or {}).get("data")
                txt = _b64url_decode(body_data) if body_data else ""

                # Determine whether this looks like an RSVP/response.
                # Primary signal: METHOD=REPLY (header param or in-body).
                # Secondary signal: PARTSTAT=ACCEPTED/DECLINED/TENTATIVE (some clients).
                header_has_reply = "method=reply" in ctype.replace(" ", "")
                body_has_reply = _has_method_reply(txt)
                body_has_partstat = _has_rsvp_partstat(txt)
                if not (header_has_reply or body_has_reply or body_has_partstat):
                    continue

                organizer = _extract_organizer_email(txt)
                if organizer == ORGANIZER_EMAIL:
                    print("yes")
                    return 0

    # If it *looks* like an RSVP from the subject AND it explicitly names our organizer
    # (e.g. "(botbhargava@gmail.com)"), treat it as a reply even if the calendar part is
    # missing. This avoids creating bogus events from plain-text RSVP notifications.
    # We computed flags per-message; easiest is to re-scan subjects quickly.
    for m in msgs:
        payload = m.get("payload") or {}
        headers = payload.get("headers") or []
        subject = _get_header(headers, "subject").strip()
        if subject and subj_re.search(subject) and subj_mentions_organizer_re.search(subject):
            print("yes")
            return 0

    print("no")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
