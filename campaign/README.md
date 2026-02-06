# HAFAS Notifications Campaign

This toolkit manages end-to-end notification campaigns for HAFAS subscriptions:

1. Define scenarios (`ctxRecon` + `serviceDays` + hysteresis).
2. Run a campaign on Android (Termux) to subscribe and poll for `rtEvents`.
3. Log device notifications externally (Tasker/AutoNotification) as NDJSON.
4. Generate a report on a PC to match events to notifications and compute metrics.

## Quickstart (Termux copy/paste)

Use this block as-is in Termux to run the monitoring.

```bash
cd ~/notification_manager/campaign
git pull

source ~/.venvs/hafas_campaign/bin/activate

# Installer/mettre à jour les deps du repo (incluant tzdata)
pip install -U pip
pip install -r requirements.txt

export HAFAS_BASE_URL="https://cfl.hafas.de/gate"
export HAFAS_AID="ALT2vl7LAFDFu2dz"
export HAFAS_USER_ID="user-22cae79f-0ccc-4959-a4e1-359a7004bb8f"
export HAFAS_CHANNEL_ID="ANDROID-d9e8ac8a-a4a7-4c05-98db-edc648b974fc"
# client.id enum used in the request envelope (NOT the ANDROID channel id)
export HAFAS_CLIENT_ID="HAFAS"

mkdir -p /sdcard/NOTIF/campaigns

python -m campaign.cli subscribe \
  --scenario ./examples/scenario_example.json \
  --out-root /sdcard/NOTIF/campaigns \
  --base-url "$HAFAS_BASE_URL" \
  --aid "$HAFAS_AID" \
  --user-id "$HAFAS_USER_ID" \
  --channel-id "$HAFAS_CHANNEL_ID" \
  --client-id "$HAFAS_CLIENT_ID"

RUN_DIR="$(ls -td /sdcard/NOTIF/campaigns/RUN_* 2>/dev/null | head -n 1)"
if [ -z "$RUN_DIR" ]; then
  echo "No RUN_* folder found under /sdcard/NOTIF/campaigns" >&2
  exit 1
fi
echo "Using run dir: $RUN_DIR"

python -m campaign.cli poll \
  --run-dir "$RUN_DIR" \
  --base-url "$HAFAS_BASE_URL" \
  --idle-grace-min 15 \
  --verbose \
  --aid "$HAFAS_AID" \
  --user-id "$HAFAS_USER_ID" \
  --channel-id "$HAFAS_CHANNEL_ID" \
  --client-id "$HAFAS_CLIENT_ID"
```

Use this block as-is in Termux to run the notification conversion

```bash
set -e

EXPORT_JSON="$(ls -t /sdcard/NOTIF/exports/*.json 2>/dev/null | head -n 1)"
[ -z "$EXPORT_JSON" ] && echo "No export JSON found in /sdcard/NOTIF/exports" && exit 1

RUN_DIR="$(ls -td /sdcard/NOTIF/campaigns/RUN_* 2>/dev/null | head -n 1)"
[ -z "$RUN_DIR" ] && echo "No RUN_* found in /sdcard/NOTIF/campaigns" && exit 1

OUT_NDJSON="$RUN_DIR/device/notifications.ndjson"
mkdir -p "$(dirname "$OUT_NDJSON")"

echo "Using export: $EXPORT_JSON"
echo "Using run:    $RUN_DIR"

python -m campaign.notification_log \
  --in "$EXPORT_JSON" \
  --out "$OUT_NDJSON" \
  --append \
  --packages "lu.cfl.cflgo.qual,de.hafas.android.cfl"

echo "OK: $EXPORT_JSON -> $OUT_NDJSON"
```

Use this block as-is in Termux to run the report

```bash
set -e

EXPORT_JSON="$(ls -t /sdcard/NOTIF/exports/*.json 2>/dev/null | head -n 1)"
[ -z "$EXPORT_JSON" ] && echo "No export JSON found in /sdcard/NOTIF/exports" && exit 1

RUN_DIR="$(ls -td /sdcard/NOTIF/campaigns/RUN_* 2>/dev/null | head -n 1)"
[ -z "$RUN_DIR" ] && echo "No RUN_* found in /sdcard/NOTIF/campaigns" && exit 1

OUT_NDJSON="$RUN_DIR/device/notifications.ndjson"
mkdir -p "$(dirname "$OUT_NDJSON")"

echo "Using export: $EXPORT_JSON"
echo "Using run:    $RUN_DIR"

python -m campaign.notification_log \
  --in "$EXPORT_JSON" \
  --out "$OUT_NDJSON" \
  --append \
  --packages "lu.cfl.cflgo.qual,de.hafas.android.cfl"

echo "OK: $EXPORT_JSON -> $OUT_NDJSON"

# -----------------------
# Generate report
# -----------------------

REPORT_DIR="$RUN_DIR/report"
mkdir -p "$REPORT_DIR"

echo "Using device: $OUT_NDJSON"
echo "Report dir:   $REPORT_DIR"

python -m campaign.report \
  --run-dir "$RUN_DIR" \
  --device-ndjson "$OUT_NDJSON" \
  --out-dir "$REPORT_DIR" \
  --match-threshold 70.0

echo "OK: $RUN_DIR -> $REPORT_DIR"
echo "Report files:"
ls -la "$REPORT_DIR"
```

## Notes

- API calls are rate limited via `pollSec` with backoff outside the window.
- Polling stops per subscription once the planned arrival window ends and no new RT activity
  has been observed for `idleGraceMin` minutes.
- `campaign.cli poll --verbose` prints one compact line per poll attempt and always appends
  a structured `poll_log.ndjson` under each `subscr_*/poll/` folder (unless `--no-save-logs`
  is set). Example line (redacted):

```json
{"tsUtc":"2026-02-05T08:49:12+00:00","tsLocal":"2026-02-05T09:49:12+01:00","subscrId":1877149,"scenarioId":"bus602_60","pollCount":12,"in_window":true,"window_start_utc":"2026-02-05T08:30:00+00:00","window_start_local":"2026-02-05T09:30:00+01:00","window_end_utc":"2026-02-05T09:30:00+00:00","window_end_local":"2026-02-05T10:30:00+01:00","dep_time_utc":"2026-02-05T08:40:00+00:00","dep_time_local":"2026-02-05T09:40:00+01:00","arr_time_utc":"2026-02-05T09:10:00+00:00","arr_time_local":"2026-02-05T10:10:00+01:00","planned_end_utc":"2026-02-05T09:40:00+00:00","planned_end_local":"2026-02-05T10:40:00+01:00","last_activity_utc":"2026-02-05T08:49:12+00:00","last_activity_local":"2026-02-05T09:49:12+01:00","idle_deadline_utc":"2026-02-05T09:04:12+00:00","idle_deadline_local":"2026-02-05T10:04:12+01:00","interval_sec":120.0,"next_due_monotonic":123456.78,"next_due_utc":"2026-02-05T08:51:12+00:00","events_total":3,"new_events":1,"dedup_skipped":2,"done":false,"done_reason":"running"}
```
- Logs redact `aid`, `user_id`, and `channel_id` in saved request/response payloads.
- Matching uses `rapidfuzz` if available, otherwise a fallback string similarity.
- Notification `id` is a stable identifier for update detection, not a global event id.
  - `nid`: Android notification ID (int) used by the app to update/replace notifications.
  - `key`: unique-ish notification key string that may include user/profile and tag; also used to detect updates.
  - Reports can count either per `id` (latest state) or treat each `postTime` as a new event depending on strategy.
- Notification Log exports may have an empty `removed[]` unless removal tracking is enabled in the app settings.
