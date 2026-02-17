#!/usr/bin/env python3
"""Deterministic fallback extraction from gog gmail thread JSON.
Reads JSON from stdin. Emits a small JSON object.

Heuristics (no LLM):
- Summary: Subject
- Date: accepts "Feb 17th" / "Feb 17" / "February 17" (year inferred from message Date header)
- Time: accepts "12:15pm" or "12:15 pm"; if only one time present, uses default duration 1h
- Location: if "no location" present, leave blank; else looks for "location: ..."
"""

import json, re, sys
from datetime import datetime, timedelta

j = json.load(sys.stdin)
thread = j.get("thread") or {}
msgs = thread.get("messages") or []
if not msgs:
    print(json.dumps({"needs_confirmation": True, "reason": "empty_thread"}))
    sys.exit(0)

msg = msgs[-1]
headers = (msg.get("payload") or {}).get("headers") or []
hmap = {h.get("name", "").lower(): h.get("value", "") for h in headers}
subject = hmap.get("subject") or "(no subject)"

def header_date_year():
    d = hmap.get("date")
    if not d:
        return None
    # Example: Tue, 17 Feb 2026 11:30:43 -0800
    try:
        return datetime.strptime(d[:25], "%a, %d %b %Y %H:%M:%S").year
    except Exception:
        try:
            return datetime.strptime(d, "%a, %d %b %Y %H:%M:%S %z").year
        except Exception:
            return None

texts = []
for m in msgs:
    sn = m.get("snippet")
    if sn:
        texts.append(sn)
text = "\n".join(texts)
text_l = text.lower()

# Location
location = None
if "no location" in text_l:
    location = None
else:
    mloc = re.search(r"\blocation\s*[:\-]\s*(.+)", text, re.I)
    if mloc:
        location = mloc.group(1).strip()

# Time range
range_re = re.compile(r"(\b\d{1,2}:\d{2}\s*(?:am|pm)\b)\s*(?:-|to)\s*(\b\d{1,2}:\d{2}\s*(?:am|pm)\b)", re.I)
mt = range_re.search(text)
start_t = end_t = None
if mt:
    start_t = mt.group(1)
    end_t = mt.group(2)
else:
    # Single time like 12:15pm
    single_time_re = re.compile(r"\b(\d{1,2}:\d{2})\s*(am|pm)\b", re.I)
    ms = single_time_re.search(text)
    if ms:
        start_t = f"{ms.group(1)}{ms.group(2)}"

# Date like "Feb 17th" or "February 17"
date = None
md = re.search(
    r"\b(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+(\d{1,2})(?:st|nd|rd|th)?\b",
    text,
    re.I,
)
if md:
    mon = md.group(1)
    day = int(md.group(2))
    year = header_date_year() or datetime.utcnow().year
    # Normalize month parsing
    try:
        date = datetime.strptime(f"{mon} {day} {year}", "%b %d %Y")
    except Exception:
        date = datetime.strptime(f"{mon} {day} {year}", "%B %d %Y")

needs = False
reason = []
if date is None:
    needs = True
    reason.append("missing_date")
if start_t is None:
    needs = True
    reason.append("missing_time")

start = end = None
if not needs:
    st = datetime.strptime(start_t.replace(" ", ""), "%I:%M%p")
    start = date.replace(hour=st.hour, minute=st.minute)
    if end_t:
        et = datetime.strptime(end_t.replace(" ", ""), "%I:%M%p")
        end = date.replace(hour=et.hour, minute=et.minute)
        if end <= start:
            end += timedelta(hours=1)
    else:
        end = start + timedelta(hours=1)

out = {
    "summary": subject,
    "location": location,
    "start": start.isoformat() if start else None,
    "end": end.isoformat() if end else None,
    "needs_confirmation": needs,
    "reason": ",".join(reason) if reason else None,
}
print(json.dumps(out))
