# openclaw_kakaji

Gmail → Google Calendar automation used by the kakaji OpenClaw agent.

## What
- Scans botbhargava@gmail.com inbox for allowed senders
- Creates calendar events (ICS preferred; otherwise LLM extraction)
- Labels processed threads

## Layout
- scripts/: main automation + parsers
- cron/: wrappers for scheduler
- docs/: notes

## Secrets
Not committed. Put OpenRouter creds in:
- `.secrets/openrouter.env`

## Run

```bash
./scripts/gmail_calendar_automation.sh
```
