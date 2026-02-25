# Email + Calendar Processing Rules (Ankush)

## Accounts

- **Watched inbox:** `botbhargava@gmail.com` (personal Gmail)
- **Calendar to create/check events in:** `botbhargava@gmail.com`

## Sender allowlist (strict)

Only process emails where the **From** is exactly one of:

- `ankush@gmail.com`
- `shuchicapri@gmail.com`
- `ankush2kn@yahoo.com`
- `ankush.bhargava@yahoo.com`

All other senders: **ignore** (no actions, no labels, no replies).

## Labeling

- After an instruction-triggered action is completed, apply Gmail label: **`processed`**

## Event detection criteria

Treat an email as containing event information if it has one or more of:

- Date/time information
- Meeting/event language
- Location details
- RSVP requests
- Appointment confirmations
- **ICS/iCalendar attachment**

## ICS handling (highest priority)

- If an email has an **ICS attachment**, use the ICS to create/send the invite.
- **Do not parse the email body** for event details if ICS is present.

## Event extraction (when NO ICS)

Extract:

- Date and time
- Event title/description
- Location (if any)
- Duration (default to **1 hour** if not specified)

### Defaults / policy parameters (machine-readable)

Edit the JSON below to change automation behavior later. The script should treat this block as the source of truth.

```json
{
  "version": 1,
  "watched_inbox": "botbhargava@gmail.com",
  "calendar_id": "botbhargava@gmail.com",

  "eligibility": {
    "require_in_inbox": true,
    "after_date": "2026/02/15",
    "window_hours": 24,
    "from_allowlist": [
      "ankush@gmail.com",
      "shuchicapri@gmail.com",
      "ankush2kn@yahoo.com",
      "ankush.bhargava@yahoo.com"
    ],
    "processed_label": "processed"
  },

  "defaults": {
    "timezone": "America/Los_Angeles",
    "timezone_resolution": "assume_timezone", 
    "tz_suffix_fallback": "-08:00",

    "duration_minutes": 60,
    "missing_end_time": "use_default_duration",

    "missing_summary": "use_body_first_line",
    "summary_fallback": "(no subject)",

    "missing_location": "leave_blank",
    "location_fallback": "",

    "missing_year": "choose_next_future_date",

    "all_day": {
      "when_ambiguous": "needs_confirmation"
    }
  },

  "ics": {
    "priority": true,
    "floating_time": "needs_confirmation"
  },

  "nlp": {
    "max_chars_to_model": 6000,
    "model": "openai/gpt-5-nano",
    "needs_confirmation_if_missing_start_or_end": true
  },

  "time_inference": {
    "lunch": {
      "start": "12:00",
      "end": "12:45"
    },
    "if_no_time_specified": "needs_confirmation"
  },

  "attendees": {
    "always_include": [
      "botbhargava@gmail.com"
    ],
    "default_attendees": [
      "ankush@gmail.com",
      "shuchicapri@gmail.com"
    ],
    "allow_add_from_body_no_ics": true,
    "copy_tokens": {
      "copy_arnav": "arnavbhargava1@gmail.com"
    },
    "attendees_add": {
      "accept_names": false,
      "unknown_names": "ignore"
    },
    "attendees_remove": {
      "resolve_names_via_contacts_md": true,
      "unknown_names": "ignore"
    }
  },

  "duplicates": {
    "enabled": true,
    "match": "summary_and_exact_start_end",
    "on_duplicate": "label_processed"
  },

  "changes": {
    "if_existing_event_differs": "needs_confirmation",
    "confirmation_channel": "telegram_dm"
  },

  "logging": {
    "write_run_folder_artifacts": true,
    "write_needs_confirmation_file": true,
    "write_error_notes": true
  }
}
```

### Time inference rules

- **"Lunch" / "lunch period"** → **12:00–12:45**
- If **no time specified** → check context for time clues; if still ambiguous, ask Ankush.
- **All-day events** only when explicitly clear (e.g., "No School", holidays).

## Invite recipients

Always include:

- `botbhargava@gmail.com`

Default recipients:

- `ankush@gmail.com`
- `shuchicapri@gmail.com`

Conditional recipients (parse from email body **only when NO ICS**):

- If body contains **"copy 'arnav'"** or **"copy arnav"** → also include `arnavbhargava1@gmail.com`
- If email explicitly mentions **"copy [email@address.com]"** → also include that address

## Duplicate detection (before creating)

- Before creating a new event, check if it already exists in `botbhargava@gmail.com` calendar.
- If meeting already exists: **DO NOT RECREATE**.

## Changed events (if an existing meeting differs)

- If an event exists but date/time/location has changed:
  - **DO NOT auto-update**
  - Ask Ankush what to do
  - Provide **old details vs new details**
  - **Wait for confirmation** before updating

## Confirmation channel

- **Changed-event confirmations** are requested via **Telegram DM** (allowlisted).
