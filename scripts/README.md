# scripts/

## Gmail→Calendar automation

Entry point:

```bash
./scripts/gmail_calendar_automation.sh
```

This is a **script-first** automation intended to run from cron without using any LLM tokens.

### Behavior (high level)
- Searches Gmail for eligible threads:
  - `in:inbox`
  - `after:2026/02/15`
  - `newer_than:2h` (configurable)
  - From strict allowlist (see `EMAIL_CALENDAR_RULES.md`)
  - Not labeled `processed`
- If an **ICS** attachment is present: downloads attachments and marks as **needs confirmation** (no ICS→Calendar import implemented yet).
- If no ICS: pulls the thread and attempts a **deterministic** extraction (very basic) from snippets.
- Creates Calendar event on `botbhargava@gmail.com` and invites `ankush@gmail.com` and `shuchicapri@gmail.com`.
- Applies Gmail label `processed` to the thread.

### Config
Environment variables:
- `ACCOUNT` (default `botbhargava@gmail.com`)
- `CALENDAR_ID` (default `botbhargava@gmail.com`)
- `WINDOW_HOURS` (default `2`)
- `AFTER_DATE` (default `2026/02/15`)
- `TZ` (default `America/Los_Angeles`)

### Notes / TODO
- ICS import: `gog` does not currently provide an ICS→Calendar import command. We may implement an ICS parser (python) that converts ICS to RFC3339 times and creates events via `gog calendar create`.
- Text extraction is currently conservative and will request confirmation when date/time isn’t explicit.
