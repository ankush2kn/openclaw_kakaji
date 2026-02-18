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
# RFC3339 offset suffix used when we parse naive local times.
# Default to Pacific time offset; update for DST if needed.
TZ_SUFFIX="${TZ_SUFFIX:--08:00}"

WINDOW_HOURS="${WINDOW_HOURS:-24}"
AFTER_DATE="${AFTER_DATE:-2026/02/15}"

ALLOWLIST_FROM=(
  "ankush@gmail.com"
  "shuchicapri@gmail.com"
  "ankush2kn@yahoo.com"
  "ankush.bhargava@yahoo.com"
)

DEFAULT_ATTENDEES=("ankush@gmail.com" "shuchicapri@gmail.com")

# For LLM extraction (OpenRouter)
OPENROUTER_MODEL="${OPENROUTER_MODEL:-openai/gpt-5-nano}"
# OPENROUTER_API_KEY must be set in the environment at runtime.

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
  # Deterministic fallback extraction implemented as a standalone script.
  "$WORKDIR/scripts/extract_basic_event_json.py"
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
    labels=set(t.get('labels') or [])
    # Avoid infinite loops: don't process already-labeled threads.
    if tid and 'processed' not in labels:
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
      # ICS path: download .ics, parse, create event, invite default attendees.
      gog gmail thread attachments "$tid" --account "$ACCOUNT" --download --out-dir "$tdir" --json >/dev/null

      # Pick the first downloaded .ics
      ics_path=$(ls -1 "$tdir"/*.ics 2>/dev/null | head -n 1 || true)
      if [[ -z "${ics_path:-}" ]]; then
        needs_conf=$((needs_conf+1))
        conf_items+=("$tid: had ICS attachment but no .ics file was downloaded.")
        continue
      fi

      event_json=$("$WORKDIR/scripts/ics_to_event.py" "$ics_path")

      # If parser returned error, request confirmation.
      if python3 - <<'PY' "$event_json"; then
import json,sys
j=json.loads(sys.argv[1])
if 'error' in j:
    raise SystemExit(1)
PY
        :
      else
        needs_conf=$((needs_conf+1))
        conf_items+=("$tid: unable to parse ICS deterministically.")
        continue
      fi

      # Extract fields
      summary=$(python3 - <<'PY' "$event_json"
import json,sys
j=json.loads(sys.argv[1])
print(j.get('summary') or '')
PY
      )
      description=$(python3 - <<'PY' "$event_json"
import json,sys
j=json.loads(sys.argv[1])
print(j.get('description') or '')
PY
      )
      location=$(python3 - <<'PY' "$event_json"
import json,sys
j=json.loads(sys.argv[1])
print(j.get('location') or '')
PY
      )

      # Determine whether all-day or dateTime
      is_all_day=$(python3 - <<'PY' "$event_json"
import json,sys
j=json.loads(sys.argv[1])
print('yes' if 'date' in (j.get('start') or {}) else 'no')
PY
      )

      if [[ "$is_all_day" == "yes" ]]; then
        start=$(python3 - <<'PY' "$event_json"
import json,sys
j=json.loads(sys.argv[1])
print(j['start']['date'])
PY
        )
        end=$(python3 - <<'PY' "$event_json"
import json,sys
j=json.loads(sys.argv[1])
print(j['end']['date'])
PY
        )
        # Create all-day event
        gog calendar create "$CALENDAR_ID" \
          --account "$ACCOUNT" \
          --summary "$summary" \
          --from "$start" \
          --to "$end" \
          --all-day \
          ${location:+--location "$location"} \
          --description "${description}\n\nSource thread: $tid" \
          --attendees "$(join_by , "${DEFAULT_ATTENDEES[@]}")" \
          --send-updates all \
          --json >"$tdir/created_event.json"
      else
        start=$(python3 - <<'PY' "$event_json"
import json,sys
j=json.loads(sys.argv[1])
print(j['start'].get('dateTime') or '')
PY
        )
        end=$(python3 - <<'PY' "$event_json"
import json,sys
j=json.loads(sys.argv[1])
print(j['end'].get('dateTime') or '')
PY
        )

        # If timeZone is missing (floating), assume configured TZ
        if [[ "$start" != *"Z"* && "$start" != *"+"* && "$start" != *"-"* ]]; then
          # ISO without offset; append TZ offset is hard — instead, fail to confirmation.
          needs_conf=$((needs_conf+1))
          conf_items+=("$tid: ICS has floating times (no TZ).")
          continue
        fi

        create_calendar_event "$summary" "$start" "$end" "$location" "${description}\n\nSource thread: $tid" >"$tdir/created_event.json"
      fi

      created=$((created+1))
      acted=$((acted+1))
      mark_thread_processed "$tid"
      continue
    fi

    # No ICS: fetch thread (full) and extract event + instructions via LLM
    gog gmail thread get "$tid" --account "$ACCOUNT" --full --json >"$tdir/thread.json"

    local event_json
    event_json=$(cat "$tdir/thread.json" | OPENROUTER_MODEL="${OPENROUTER_MODEL:-openai/gpt-5-nano}" OPENROUTER_API_KEY="${OPENROUTER_API_KEY:-}" "$WORKDIR/scripts/llm_extract_event.py")

    local needs
    needs=$(python3 - <<'PY' "$event_json"
import json,sys
j=json.loads(sys.argv[1])
print('yes' if j.get('needs_confirmation') else 'no')
PY
    )

    if [[ "$needs" == "yes" ]]; then
      needs_conf=$((needs_conf+1))
      reason=$(python3 - <<'PY' "$event_json"
import json,sys
j=json.loads(sys.argv[1])
print(j.get('reason') or 'unknown')
PY
      )
      conf_items+=("$tid: needs confirmation ($reason).")
      continue
    fi

    local summary start end location agenda
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
    agenda=$(python3 - <<'PY' "$event_json"
import json,sys
j=json.loads(sys.argv[1]); print(j.get('agenda') or '')
PY
    )

    # Attendee instructions
    local add_csv remove_csv send_updates
    add_csv=$(python3 - <<'PY' "$event_json"
import json,sys
j=json.loads(sys.argv[1]); print(','.join(j.get('attendees_add') or []))
PY
    )
    remove_csv=$(python3 - <<'PY' "$event_json"
import json,sys
j=json.loads(sys.argv[1]); print(','.join(j.get('attendees_remove') or []))
PY
    )
    send_updates=$(python3 - <<'PY' "$event_json"
import json,sys
j=json.loads(sys.argv[1]); print(j.get('send_updates') or '')
PY
    )

    # Apply remove list to DEFAULT_ATTENDEES; append any add list
    # shellcheck disable=SC2207
    local attendees=("${DEFAULT_ATTENDEES[@]}")
    if [[ -n "$remove_csv" ]]; then
      IFS=',' read -r -a _rm <<<"$remove_csv"
      for rm in "${_rm[@]}"; do
        rm=${rm// /}
        if [[ -z "$rm" ]]; then continue; fi
        local filtered=()
        for a in "${attendees[@]}"; do
          if [[ "${a,,}" != "${rm,,}" ]]; then filtered+=("$a"); fi
        done
        attendees=("${filtered[@]}")
      done
    fi
    if [[ -n "$add_csv" ]]; then
      IFS=',' read -r -a _add <<<"$add_csv"
      for ad in "${_add[@]}"; do
        ad=${ad// /}
        [[ -z "$ad" ]] && continue
        attendees+=("$ad")
      done
    fi

    # De-dup attendees
    local deduped=()
    for a in "${attendees[@]}"; do
      local seen=0
      for b in "${deduped[@]}"; do
        if [[ "${a,,}" == "${b,,}" ]]; then seen=1; break; fi
      done
      [[ $seen -eq 0 ]] && deduped+=("$a")
    done
    attendees=("${deduped[@]}")

    # Sanity: require start/end
    if [[ -z "$start" || -z "$end" ]]; then
      needs_conf=$((needs_conf+1))
      conf_items+=("$tid: missing start/end after LLM extraction.")
      continue
    fi

    # Duplicate check: search calendar for same summary, and match exact start/end.
    if gog calendar search "$summary" --account "$ACCOUNT" --json | python3 - <<'PY' "$start" "$end"
import json,sys
start=sys.argv[1]; end=sys.argv[2]
res=json.load(sys.stdin).get('events') or []
for e in res:
    s=(e.get('start') or {}).get('dateTime')
    t=(e.get('end') or {}).get('dateTime')
    if s==start and t==end:
        sys.exit(0)
sys.exit(1)
PY
    then
      mark_thread_processed "$tid"
      acted=$((acted+1))
      continue
    fi

    # Create event with custom attendees + optional send_updates
    attendees_csv="$(join_by , "${attendees[@]}")"

    if [[ -n "$send_updates" ]]; then
      gog calendar create "$CALENDAR_ID" \
        --account "$ACCOUNT" \
        --summary "$summary" \
        --from "$start" \
        --to "$end" \
        ${location:+--location "$location"} \
        --description "${agenda:-}\n\nSource thread: $tid" \
        --attendees "$attendees_csv" \
        --send-updates "$send_updates" \
        --json >"$tdir/created_event.json"
    else
      gog calendar create "$CALENDAR_ID" \
        --account "$ACCOUNT" \
        --summary "$summary" \
        --from "$start" \
        --to "$end" \
        ${location:+--location "$location"} \
        --description "${agenda:-}\n\nSource thread: $tid" \
        --attendees "$attendees_csv" \
        --send-updates all \
        --json >"$tdir/created_event.json"
    fi

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
