#!/usr/bin/env python3
"""LLM-based extraction of calendar event + special instructions from a Gmail thread.

Inputs:
- Gmail thread JSON on stdin (from `gog gmail thread get --full --json`)

Outputs:
- A single JSON object on stdout.

Requires:
- OPENROUTER_API_KEY env var

Model:
- OPENROUTER_MODEL (default: openai/gpt-5-nano)

This script is intentionally lightweight and deterministic in its I/O:
- It ALWAYS prints JSON.
- On any failure, it emits needs_confirmation=true with a reason.
"""

import base64
import json
import os
import re
import sys
import urllib.request

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "").strip()
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "openai/gpt-5-nano").strip()


def _b64url_decode(data: str) -> str:
    # Gmail uses URL-safe base64 without padding sometimes
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


def extract_thread_text(thread_json: dict) -> dict:
    """Return {subject, from, date, text} for prompting."""
    thread = thread_json.get("thread") or thread_json
    msgs = thread.get("messages") or []
    if not msgs:
        return {"subject": "", "from": "", "date": "", "text": ""}

    # Prefer the last message as "latest state"; also include snippets across messages.
    latest = msgs[-1]
    headers = (latest.get("payload") or {}).get("headers") or []
    hmap = {h.get("name", "").lower(): h.get("value", "") for h in headers}

    subject = hmap.get("subject", "")
    from_ = hmap.get("from", "")
    date = hmap.get("date", "")

    snippets = []
    for m in msgs:
        sn = m.get("snippet")
        if sn:
            snippets.append(sn)

    # Attempt to extract text/plain bodies (best effort)
    bodies = []
    for m in msgs:
        payload = m.get("payload") or {}
        for part in _walk_parts(payload):
            mt = (part.get("mimeType") or "").lower()
            body = (part.get("body") or {}).get("data")
            if mt.startswith("text/plain") and body:
                bodies.append(_b64url_decode(body))

    # Keep prompt small: cap content
    text = "\n\n".join([*snippets, *bodies]).strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Hard cap to keep costs predictable
    if len(text) > 6000:
        text = text[:6000] + "\n\n[TRUNCATED]"

    return {"subject": subject, "from": from_, "date": date, "text": text}


def call_openrouter(prompt: dict) -> dict:
    if not OPENROUTER_API_KEY:
        return {
            "needs_confirmation": True,
            "reason": "missing_openrouter_api_key",
        }

    system = (
        "You extract calendar-event details and special instructions from an email thread. "
        "Return ONLY valid JSON, matching the schema exactly. "
        "Do not include markdown, comments, or extra keys. "
        "If any required event detail is missing or ambiguous, set needs_confirmation=true."
    )

    schema = {
        "needs_confirmation": "boolean",
        "reason": "string|null",
        "summary": "string|null",
        "start": "RFC3339 datetime with timezone offset or Z, or null",
        "end": "RFC3339 datetime with timezone offset or Z, or null",
        "location": "string|null",
        "agenda": "string|null",
        "attendees_add": "array of email strings (can be empty)",
        "attendees_remove": "array of email strings (lowercase emails only; MUST be full email addresses)",
        "send_updates": "one of: all|externalOnly|none|null",
    }

    user = {
        "task": (
            "From the email content, extract: summary, start, end, location, agenda. "
            "Also detect special instructions about who to invite or avoid inviting. "
            "If the sender explicitly says not to invite someone, put their FULL EMAIL ADDRESS in attendees_remove (lowercase). "
            "If the sender says invite someone specific, put them in attendees_add. "
            "If start/end time, timezone, or date are unclear, set needs_confirmation=true and explain briefly in reason. "
            "If only a start time is given, assume a 60-minute duration and provide end=start+60min."
        ),
        "email": prompt,
        "output_schema": schema,
    }

    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
        ],
        "temperature": 0,
        "max_tokens": 500,
    }

    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            # Identifiers are optional but helpful
            "HTTP-Referer": "https://openclaw.local",
            "X-Title": "openclaw-gmail-calendar",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        data = json.loads(raw)
        msg = data["choices"][0]["message"]
        content = msg.get("content")
        if not content:
            # Some providers may return tool/empty content on truncation.
            return {"needs_confirmation": True, "reason": "openrouter_empty_content"}
        out = json.loads(content)
        return out
    except Exception as e:
        return {
            "needs_confirmation": True,
            "reason": f"openrouter_error:{type(e).__name__}",
        }


def main():
    try:
        thread_json = json.load(sys.stdin)
    except Exception:
        print(json.dumps({"needs_confirmation": True, "reason": "invalid_input_json"}))
        return

    prompt = extract_thread_text(thread_json)
    out = call_openrouter(prompt)

    # Normalize output (ensure required keys exist)
    def g(k, default):
        return out.get(k, default) if isinstance(out, dict) else default

    result = {
        "needs_confirmation": bool(g("needs_confirmation", True)),
        "reason": g("reason", None),
        "summary": g("summary", None),
        "start": g("start", None),
        "end": g("end", None),
        "location": g("location", None),
        "agenda": g("agenda", None),
        "attendees_add": g("attendees_add", []) or [],
        "attendees_remove": g("attendees_remove", []) or [],
        "send_updates": g("send_updates", None),
    }

    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
