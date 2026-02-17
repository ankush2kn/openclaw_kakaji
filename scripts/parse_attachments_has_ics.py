#!/usr/bin/env python3
import json, sys

raw = sys.stdin.read().strip()
if not raw:
    print("no")
    sys.exit(0)

j = json.loads(raw)
files = j.get("attachments") or j.get("files") or []
for f in files:
    name = (f.get("filename") or "").lower()
    mime = (f.get("mimeType") or "").lower()
    if name.endswith(".ics") or ("calendar" in mime) or ("ics" in mime):
        print("yes")
        sys.exit(0)
print("no")
