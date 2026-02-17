#!/usr/bin/env bash
set -euo pipefail

# Gmail→Calendar automation (script-first)
# Uses gog CLI (OAuth already configured) to:
# - find eligible Gmail threads
# - parse for ICS (priority) or fall back to basic text parsing
# - create calendar events + invite attendees
# - label threads as processed

WORKDIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RULES_FILE="$WORKDIR/EMAIL_CALENDAR_RULES.md"

ACCOUNT="${ACCOUNT:-botbhargava@gmail.com}"
CALENDAR_ID="${CALENDAR_ID:-botbhargava@gmail.com}"
TZ="${TZ:-America/Los_Angeles}"

WINDOW_HOURS="${WINDOW_HOURS:-2}"
AFTER_DATE="${AFTER_DATE:-2026/02/15}"

ALLOWLIST_FROM=(
  "ankush@gmail.com"
  "shuchicapri@gmail.com"
  "ankush2kn@yahoo.com"
  "ankush.bhargava@yahoo.com"
)

DEFAULT_ATTENDEES=("ankush@gmail.com" "shuchicapri@gmail.com")

PROCESSED_LABEL="processed"

OUTDIR_BASE="$WORKDIR/tmp/automation"
RUN_TS="$(date -u +"%Y%m%dT%H%M%SZ")"
OUTDIR="$OUTDIR_BASE/$RUN_TS"
mkdir -p "$OUTDIR"

log() { printf '%s\n' "$*" >&2; }

require() {
  command -v "$1" >/dev/null 2>&1 || { echo "Missing required command: $1" >&2; exit 127; }
}

join_by() {
  local IFS="$1"; shift; echo "$*";
}

gmail_query() {
  # Gmail query: inbox, after date cutoff, newer_than window, from allowlist OR, exclude already processed
  local or_from=""
  for addr in "${ALLOWLIST_FROM[@]}"; do
    if [[ -z "$or_from" ]]; then
      or_from="from:$addr"
    else
      or_from+=" OR from:$addr"
    fi
  done
  # Parentheses required around OR chain.
  echo "in:inbox after:$AFTER_DATE newer_than:${WINDOW_HOURS}h -label:$PROCESSED_LABEL (${or_from})"
}

ensure_processed_label() {
  # Create label if missing.
  if ! gog gmail labels get "$PROCESSED_LABEL" --account "$ACCOUNT" --json >/dev/null 2>&1; then
    log "Creating Gmail label: $PROCESSED_LABEL"
    gog gmail labels create "$PROCESSED_LABEL" --account "$ACCOUNT" --json >/dev/null
  fi
}

search_threads() {
  local q
  q="$(gmail_query)"
  # Returns JSON array under threads
  gog gmail search "$q" --account "$ACCOUNT" --json
}

thread_has_ics() {
  local thread_id="$1"
  # NOTE: piping to python with heredocs is brittle in bash; call a script.
  gog gmail thread attachments "$thread_id" --account "$ACCOUNT" --json \
    | "$WORKDIR/scripts/parse_attachments_has_ics.py"
}

download_thread_attachments() {
  local thread_id="$1"
  local outdir="$2"
  mkdir -p "$outdir"
  gog gmail thread get "$thread_id" --account "$ACCOUNT" --download --out-dir "$outdir" --json >/dev/null
}

extract_basic_event_json() {
  # Very lightweight, deterministic fallback extraction.
  # Reads a thread JSON (with --full) and tries to extract:
  # - title from Subject
  # - location: first line containing 'Location:' or an address-like line
  # - start/end date+time: tries to find explicit date (YYYY-MM-DD or Month Day, Year) and time range (e.g. 9:00 AM - 4:00 PM)
  # Output JSON: {summary, location, start, end, needs_confirmation, reason}
  python3 - "$@" <<'PY'
import json,re,sys
from datetime import datetime,timedelta

thread=json.load(sys.stdin).get('thread') or {}
msgs=thread.get('messages') or []
if not msgs:
    print(json.dumps({"needs_confirmation": True, "reason": "empty_thread"}))
    sys.exit(0)

# Use last message headers preferentially
headers=(msgs[-1].get('payload') or {}).get('headers') or []
hmap={h.get('name','').lower(): h.get('value','') for h in headers}
subject=hmap.get('subject') or '(no subject)'

# Combine snippet + any plain text parts if present in gog output
texts=[]
for m in msgs:
    sn=m.get('snippet')
    if sn: texts.append(sn)
text='\n'.join(texts)

# Find time range
time_re=re.compile(r'(\b\d{1,2}:\d{2}\s*(?:AM|PM)\b)\s*(?:-|to)\s*(\b\d{1,2}:\d{2}\s*(?:AM|PM)\b)', re.I)
mt=time_re.search(text)
start_t=end_t=None
if mt:
    start_t=mt.group(1).upper().replace(' ', '')
    end_t=mt.group(2).upper().replace(' ', '')

# Find explicit date like "February 17, 2026" or "Feb 17, 2026"
date_re=re.compile(r'\b(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+(\d{1,2}),\s*(\d{4})\b', re.I)
md=date_re.search(text)
date=None
if md:
    mon=md.group(1)
    day=int(md.group(2))
    year=int(md.group(3))
    date=datetime.strptime(f"{mon} {day} {year}", "%b %d %Y") if len(mon)<=3 else datetime.strptime(f"{mon} {day} {year}", "%B %d %Y")

# Location heuristic
loc=None
loc_re=re.compile(r'\bLocation\s*:\s*(.+)', re.I)
ml=loc_re.search(text)
if ml:
    loc=ml.group(1).strip()

needs=False
reason=[]
if date is None:
    needs=True; reason.append('missing_date')
if start_t is None or end_t is None:
    needs=True; reason.append('missing_time_range')

def parse_time(t):
    return datetime.strptime(t, "%I:%M%p")

start=None; end=None
if not needs:
    st=parse_time(start_t)
    et=parse_time(end_t)
    start=date.replace(hour=st.hour, minute=st.minute)
    end=date.replace(hour=et.hour, minute=et.minute)
    if end <= start:
        end = end + timedelta(hours=1)

out={
  "summary": subject,
  "location": loc,
  "start": start.isoformat() if start else None,
  "end": end.isoformat() if end else None,
  "needs_confirmation": needs,
  "reason": ','.join(reason) if reason else None,
}
print(json.dumps(out))
PY
}

create_calendar_event() {
  local summary="$1"; local start="$2"; local end="$3"; local location="$4"; local description="$5"; shift 5
  local attendees_csv
  attendees_csv="$(join_by , "${DEFAULT_ATTENDEES[@]}")"

  gog calendar create "$CALENDAR_ID" \
    --account "$ACCOUNT" \
    --summary "$summary" \
    --from "$start" \
    --to "$end" \
    ${location:+--location "$location"} \
    --description "$description" \
    --attendees "$attendees_csv" \
    --send-updates all \
    --json
}

mark_thread_processed() {
  local thread_id="$1"
  gog gmail thread modify "$thread_id" --account "$ACCOUNT" --add "$PROCESSED_LABEL" --json >/dev/null
}

main() {
  require gog
  require python3

  if [[ ! -f "$RULES_FILE" ]]; then
    log "WARNING: $RULES_FILE not found. Proceeding with built-in defaults." 
  fi

  ensure_processed_label

  local search_json="$OUTDIR/search.json"
  search_threads | tee "$search_json" >/dev/null

  local thread_ids
  thread_ids=$(python3 - <<'PY' "$search_json"
import json,sys
p=sys.argv[1]
with open(p,'r',encoding='utf-8') as f:
    j=json.load(f)
threads=j.get('threads') or []
for t in threads:
    tid=t.get('id')
    if tid:
        print(tid)
PY
  )

  local scanned=0 acted=0 created=0 needs_conf=0
  local conf_items=()

  for tid in $thread_ids; do
    scanned=$((scanned+1))
    local tdir="$OUTDIR/thread_$tid"
    mkdir -p "$tdir"

    # Check for ICS
    if [[ "$(thread_has_ics "$tid")" == "yes" ]]; then
      # Download ICS attachments. We don't need to do anything else: calendar invites typically
      # auto-create the event in Google Calendar once received/accepted.
      gog gmail thread attachments "$tid" --account "$ACCOUNT" --download --out-dir "$tdir" --json >/dev/null
      mark_thread_processed "$tid"
      acted=$((acted+1))
      continue
    fi

    # No ICS: fetch thread (full) and try basic deterministic parse
    gog gmail thread get "$tid" --account "$ACCOUNT" --full --json >"$tdir/thread.json"

    local event_json
    event_json=$(cat "$tdir/thread.json" | extract_basic_event_json)

    local ok
    ok=$(python3 - <<'PY' "$event_json"
import json,sys
j=json.loads(sys.argv[1])
print('ok' if not j.get('needs_confirmation') else 'no')
PY
    )

    if [[ "$ok" != "ok" ]]; then
      needs_conf=$((needs_conf+1))
      reason=$(python3 - <<'PY' "$event_json"
import json,sys
j=json.loads(sys.argv[1])
print(j.get('reason') or 'unknown')
PY
      )
      conf_items+=("$tid: unable to extract event deterministically ($reason).")
      continue
    fi

    local summary start end location
    summary=$(python3 - <<'PY' "$event_json"
import json,sys
j=json.loads(sys.argv[1]); print(j.get('summary') or '')
PY
    )
    start=$(python3 - <<'PY' "$event_json"
import json,sys
j=json.loads(sys.argv[1]); print(j.get('start') or '')
PY
    )
    end=$(python3 - <<'PY' "$event_json"
import json,sys
j=json.loads(sys.argv[1]); print(j.get('end') or '')
PY
    )
    location=$(python3 - <<'PY' "$event_json"
import json,sys
j=json.loads(sys.argv[1]); print(j.get('location') or '')
PY
    )

    # Duplicate check: search calendar for same summary near start time (simple heuristic)
    # NOTE: gog search is query-based, so we'll do a best-effort search by summary.
    if gog calendar search "$summary" --account "$ACCOUNT" --json | python3 - <<'PY' "$start" "$end"
import json,sys
from datetime import datetime
start=sys.argv[1]; end=sys.argv[2]
res=json.load(sys.stdin).get('events') or []
# If any event matches exact start/end, treat as duplicate.
for e in res:
    s=(e.get('start') or {}).get('dateTime')
    t=(e.get('end') or {}).get('dateTime')
    if s==start and t==end:
        sys.exit(0)
sys.exit(1)
PY
    then
      # duplicate: just mark processed
      mark_thread_processed "$tid"
      acted=$((acted+1))
      continue
    fi

    # Create event
    create_calendar_event "$summary" "$start" "$end" "$location" "Source thread: $tid" >"$tdir/created_event.json"
    created=$((created+1))
    acted=$((acted+1))

    mark_thread_processed "$tid"
  done

  echo "Scanned: $scanned eligible threads"
  echo "Acted on: $acted"
  echo "Events created: $created"
  echo "Needs confirmation: $needs_conf"
  if [[ $needs_conf -gt 0 ]]; then
    printf '%s\n' "" "Items needing confirmation:" 
    printf '%s\n' "- ${conf_items[@]}"
  fi
}

main "$@"
