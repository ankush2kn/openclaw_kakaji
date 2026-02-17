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
