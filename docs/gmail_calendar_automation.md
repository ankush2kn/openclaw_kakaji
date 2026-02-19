# Gmail → Calendar automation (botbhargava@gmail.com)

This documents how `scripts/gmail_calendar_automation.sh` turns certain incoming emails into Google Calendar events.

## Entry point

```bash
cd /home/ubuntu/.openclaw/workspace
./scripts/gmail_calendar_automation.sh
```

## What it does (high level)

1. Searches Gmail inbox for eligible threads.
2. For each eligible thread:
   - If it contains an `.ics` attachment: parse it deterministically and create an event.
   - Otherwise: extract event + instructions using an LLM (OpenRouter).
3. Creates/updates Google Calendar event and invites attendees.
4. Labels the Gmail thread as `processed`.

## Eligibility rules

Gmail query is built in `gmail_calendar_automation.sh` and currently includes:
- `in:inbox`
- `after:<AFTER_DATE>`
- `newer_than:<WINDOW_HOURS>h`
- from a fixed allowlist (`ALLOWLIST_FROM` array)
- excludes items already labeled `processed`

## Processing logic per thread

### A) ICS path (preferred)

If the thread has an `.ics` attachment (detected by `scripts/parse_attachments_has_ics.py`):

- Download attachments into the run folder.
- Parse the first `.ics` file with `scripts/ics_to_event.py`.
- If parsing is successful:
  - Create a Calendar event via `gog calendar create`.
  - Invite default attendees.
  - Label thread `processed`.
- If parsing fails or timezones are ambiguous ("floating" times):
  - Increment `Needs confirmation` and do NOT create an event.

### B) Non-ICS path (LLM extraction)

If there is no `.ics` attachment:

- Fetch the full thread JSON (`gog gmail thread get --full --json`).
- Extract event details + instructions using:
  - `scripts/llm_extract_event.py`
  - OpenRouter model set by env `OPENROUTER_MODEL` (currently `google/gemini-2.5-flash`).
  - The email content sent to the LLM is capped to **6000 characters**.

The LLM returns JSON with:
- `summary`, `start`, `end`, `location`, `agenda`
- `attendees_add`: list of emails to add
- `attendees_remove`: list of tokens (either emails OR names like `Shuchi`)
- `needs_confirmation` / `reason`

If `needs_confirmation=true` OR start/end are missing:
- Do not create the event.
- Add an item to the confirmation list.

## Attendee rules

### Defaults

`DEFAULT_ATTENDEES` are always the initial invite list.

### Removing attendees (deterministic)

The LLM may return `attendees_remove` entries as either:
- full email addresses (e.g. `shuchicapri@gmail.com`), or
- names (e.g. `Shuchi`).

Names are resolved deterministically using:
- `/home/ubuntu/.openclaw/workspace/CONTACTS.md`
- `/home/ubuntu/.openclaw/workspace/scripts/resolve_contact.py`

If a name is not found in `CONTACTS.md`, removal is skipped (no guessing).

### Adding attendees

Emails in `attendees_add` are appended to the list and then de-duped.

## Duplicate protection

For non-ICS events, the script does a best-effort duplicate check:
- Search calendar by `summary`
- If an existing event has the exact same `start` and `end`, treat as duplicate:
  - do not create a new event
  - label thread `processed`

## Credentials / secrets

### Google access

The script relies on `gog` being pre-authenticated for:
- Gmail
- Calendar

### OpenRouter (LLM extraction)

Cron environments often do not inherit your shell env, so the script loads:

- `/home/ubuntu/.openclaw/workspace/.secrets/openrouter.env`

This file should contain:
```bash
export OPENROUTER_API_KEY='...'
export OPENROUTER_MODEL='google/gemini-2.5-flash'
```

This folder is gitignored.

## Output / run artifacts

By default the script writes per-run artifacts under:
- `/home/ubuntu/.openclaw/workspace/tmp/automation/<RUN_TS>/`

This includes:
- `search.json` (results of Gmail search)
- per-thread folders (downloaded thread JSON, attachments, created event JSON)

(See below for the new no-op behavior.)
