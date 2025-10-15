#!/usr/bin/env bash
set -euo pipefail
SERVER_USER="${SERVER_USER:-root}"
SERVER_HOST="${SERVER_HOST:-voiprnd.nemtclouddispatch.com}"
PROJECT_PATH="${PROJECT_PATH:-/root/Asterisk-AI-Voice-Agent}"
SINCE_MIN="${SINCE_MIN:-60}"
TS=$(date -u +%Y%m%d-%H%M%S)
BASE="logs/remote/rca-$TS"
mkdir -p "$BASE"/{taps,recordings,logs}
echo "$BASE" > logs/remote/rca-latest.path
ssh "$SERVER_USER@$SERVER_HOST" "docker logs --since ${SINCE_MIN}m ai_engine > /tmp/ai-engine.latest.log" || true
scp "$SERVER_USER@$SERVER_HOST:/tmp/ai-engine.latest.log" "$BASE/logs/ai-engine.log"
CID=$(grep -o '"call_id": "[^"]*"' "$BASE/logs/ai-engine.log" | awk -F '"' '{print $4}' | tail -n 1 || true)
echo -n "$CID" > "$BASE/call_id.txt"
ssh "$SERVER_USER@$SERVER_HOST" "docker exec ai_engine sh -lc 'cd /tmp/ai-engine-taps 2>/dev/null || exit 0; tar czf /tmp/ai_taps_${CID}.tgz *${CID}*.wav 2>/dev/null || true'; docker cp ai_engine:/tmp/ai_taps_${CID}.tgz /tmp/ai_taps_${CID}.tgz 2>/dev/null || true" || true
scp "$SERVER_USER@$SERVER_HOST:/tmp/ai_taps_${CID}.tgz" "$BASE/" 2>/dev/null || true
if [ -f "$BASE/ai_taps_${CID}.tgz" ]; then tar xzf "$BASE/ai_taps_${CID}.tgz" -C "$BASE/taps"; fi
REC_LIST=$(ssh "$SERVER_USER@$SERVER_HOST" "find /var/spool/asterisk/monitor -type f -name '*${CID}*.wav' -printf '%p\\n' 2>/dev/null | head -n 10") || true
if [ -n "$REC_LIST" ]; then
  while IFS= read -r f; do
    [ -z "$f" ] && continue
    scp "$SERVER_USER@$SERVER_HOST:$f" "$BASE/recordings/" || true
  done <<< "$REC_LIST"
fi
TAPS=$(ls "$BASE"/taps/*.wav 2>/dev/null || true)
RECS=$(ls "$BASE"/recordings/*.wav 2>/dev/null || true)
if [ -n "$TAPS" ]; then python3 scripts/wav_quality_analyzer.py "$BASE"/taps/*.wav --json "$BASE/wav_report_taps.json" --frame-ms 20 || true; fi
if [ -n "$RECS" ]; then python3 scripts/wav_quality_analyzer.py "$BASE"/recordings/*.wav --json "$BASE/wav_report_rec.json" --frame-ms 20 || true; fi
# Build call timeline with key events for the captured call
if [ -n "$CID" ]; then
  egrep -n "ADAPTIVE WARM-UP|Wrote .*200ms|call-level summary|STREAMING TUNING SUMMARY" "$BASE/logs/ai-engine.log" | grep "$CID" > "$BASE/logs/call_timeline.log" || true
fi

# Fetch Deepgram usage detail for the latest call when credentials are available.
DG_PROJECT_ID="${DG_PROJECT_ID:-}"
DG_API_KEY="${DEEPGRAM_API_KEY:-}"
if [ -n "$CID" ] && [ -n "$DG_PROJECT_ID" ] && [ -n "$DG_API_KEY" ]; then
  START_ISO=$(date -u -v-30M +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null || python3 - <<'PYCODE'
import datetime
print((datetime.datetime.utcnow() - datetime.timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ"))
PYCODE
)
  END_ISO=$(date -u +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null || python3 - <<'PYCODE'
import datetime
print(datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"))
PYCODE
)
  curl --silent --show-error --request GET \
    "https://api.deepgram.com/v1/projects/${DG_PROJECT_ID}/requests?start=${START_ISO}&end=${END_ISO}&status=succeeded" \
    --header "Authorization: Token ${DG_API_KEY}" \
    --header 'accept: application/json' \
    | jq '.requests // [] | map(select(.request_id != null))' > "$BASE/logs/deepgram_requests.json" || true
  if command -v jq >/dev/null 2>&1; then
    REQUEST_ID=$(jq -r '.[0].request_id // empty' "$BASE/logs/deepgram_requests.json" 2>/dev/null || true)
    if [ -n "$REQUEST_ID" ]; then
      curl --silent --show-error --request GET \
        "https://api.deepgram.com/v1/projects/${DG_PROJECT_ID}/requests/${REQUEST_ID}" \
        --header "Authorization: Token ${DG_API_KEY}" \
        --header 'accept: application/json' \
        > "$BASE/logs/deepgram_request_detail.json" || true
    fi
  fi
fi
echo "RCA_BASE=$BASE"
echo "CALL_ID=$CID"
