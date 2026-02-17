#!/usr/bin/env python3
"""Parse a minimal subset of ICS (VEVENT) and emit JSON suitable for calendar creation.

This is intentionally small and dependency-light (no icalendar library).
Supports common fields:
- SUMMARY
- DESCRIPTION
- LOCATION
- DTSTART / DTEND (date-time w/ TZID or UTC Z)
- DTSTART / DTEND (date-only all-day)

Output JSON:
{
  "summary": str,
  "description": str|None,
  "location": str|None,
  "start": {"dateTime": "RFC3339", "timeZone": "America/Los_Angeles"} | {"date": "YYYY-MM-DD"},
  "end":   {"dateTime": "RFC3339", "timeZone": "America/Los_Angeles"} | {"date": "YYYY-MM-DD"}
}

Notes:
- Handles folded lines per RFC5545.
- Only first VEVENT is processed.
"""

import json
import re
import sys
from datetime import datetime
from zoneinfo import ZoneInfo


def unfold_ics(text: str) -> list[str]:
    # Lines that start with space or tab are continuations of previous line.
    out = []
    cur = ""
    for line in text.splitlines():
        if line.startswith((" ", "\t")):
            cur += line[1:]
        else:
            if cur:
                out.append(cur)
            cur = line.rstrip("\r")
    if cur:
        out.append(cur)
    return out


def parse_prop(line: str):
    # e.g. DTSTART;TZID=America/Los_Angeles:20260217T090000
    if ":" not in line:
        return None
    left, value = line.split(":", 1)
    parts = left.split(";")
    name = parts[0].upper()
    params = {}
    for p in parts[1:]:
        if "=" in p:
            k, v = p.split("=", 1)
            params[k.upper()] = v
    return name, params, value


def parse_dt(value: str, tzid: str | None):
    value = value.strip()
    # date-only
    if re.fullmatch(r"\d{8}", value):
        d = datetime.strptime(value, "%Y%m%d").date()
        return {"date": d.isoformat()}

    # date-time
    if value.endswith("Z"):
        dt = datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=ZoneInfo("UTC"))
        return {"dateTime": dt.isoformat().replace("+00:00", "Z"), "timeZone": "UTC"}

    # floating or TZID
    dt = datetime.strptime(value, "%Y%m%dT%H%M%S")
    if tzid:
        z = ZoneInfo(tzid)
        dt = dt.replace(tzinfo=z)
        return {"dateTime": dt.isoformat(), "timeZone": tzid}

    # No TZID: treat as naive local; caller can override.
    return {"dateTime": dt.isoformat(), "timeZone": None}


def main():
    if len(sys.argv) < 2:
        print("Usage: ics_to_event.py <path-to-ics>", file=sys.stderr)
        sys.exit(2)

    path = sys.argv[1]
    raw = open(path, "r", encoding="utf-8", errors="replace").read()
    lines = unfold_ics(raw)

    in_event = False
    props = {}
    for line in lines:
        u = line.strip()
        if u.upper() == "BEGIN:VEVENT":
            in_event = True
            continue
        if u.upper() == "END:VEVENT":
            break
        if not in_event:
            continue
        parsed = parse_prop(u)
        if not parsed:
            continue
        name, params, value = parsed
        # store first occurrence
        if name not in props:
            props[name] = (params, value)

    if not props:
        print(json.dumps({"error": "no_vevent_found"}))
        sys.exit(1)

    summary = (props.get("SUMMARY") or ({}, "(no summary)"))[1]
    description = (props.get("DESCRIPTION") or ({}, None))[1]
    location = (props.get("LOCATION") or ({}, None))[1]

    dtstart_params, dtstart_val = props.get("DTSTART", ({}, None))
    dtend_params, dtend_val = props.get("DTEND", ({}, None))
    if not dtstart_val or not dtend_val:
        print(json.dumps({"error": "missing_dtstart_or_dtend"}))
        sys.exit(1)

    start = parse_dt(dtstart_val, dtstart_params.get("TZID"))
    end = parse_dt(dtend_val, dtend_params.get("TZID"))

    out = {
        "summary": summary,
        "description": description,
        "location": location,
        "start": start,
        "end": end,
    }
    print(json.dumps(out))


if __name__ == "__main__":
    main()
