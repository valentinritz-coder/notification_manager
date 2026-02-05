# HAFAS Notifications Campaign

This toolkit manages end-to-end notification campaigns for HAFAS subscriptions:

1. Define scenarios (`ctxRecon` + `serviceDays` + hysteresis).
2. Run a campaign on Android (Termux) to subscribe and poll for `rtEvents`.
3. Log device notifications externally (Tasker/AutoNotification) as NDJSON.
4. Generate a report on a PC to match events to notifications and compute metrics.

## Structure

```
campaign/
  src/campaign/
  examples/
  scripts/
```

## Install (Termux)

```sh
pkg update
pkg install python git
pip install -r requirements.txt
```

## Scenario format

See `examples/scenario_example.json` for a working template.

```json
{
  "campaignName": "morning_peak",
  "pollSec": 120,
  "preWindowMin": 10,
  "postWindowMin": 30,
  "maxRuntimeMin": 240,
  "items": [
    {
      "scenarioId": "nancy_lux_ter88576",
      "beginDate": "20260205",
      "endDate": "20260205",
      "nPass": 1,
      "hysteresis": { "notificationStart": 60, "minDeviationInterval": 5 },
      "ctxRecon": "¶HKI¶T$A=1@O=...#¶KRCC¶#VE#1#"
    }
  ]
}
```

## Running a campaign (Android)

1. Subscribe:

```sh
python -m campaign.cli subscribe \
  --scenario ./examples/scenario_example.json \
  --out-root /sdcard/NOTIF/campaigns \
  --base-url "https://www.cfl.lu/gate" \
  --aid "YOUR_AID" \
  --user-id "YOUR_USER_ID" \
  --channel-id "YOUR_CHANNEL_ID"
```

2. Poll (use the run dir printed by `subscribe`):

```sh
python -m campaign.cli poll \
  --run-dir /sdcard/NOTIF/campaigns/RUN_20260205_080000__morning_peak \
  --base-url "https://www.cfl.lu/gate" \
  --aid "YOUR_AID" \
  --user-id "YOUR_USER_ID" \
  --channel-id "YOUR_CHANNEL_ID"
```

### Output layout

Each run is stored under a unique folder:

```
RUN_YYYYMMDD_HHMMSS__<campaignName>/
  scenario.json
  subs/
    subscr_<subscrId>/
      manifest.json
      raw/
      poll/
        rt_events.ndjson
        state.json
  device/
    notifications.ndjson
  report/
```

## Device notification logging (Android)

Use a notification logger (Tasker/AutoNotification or any NDJSON logger) to append lines like:

```json
{"tsDevice":"2026-02-05T08:42:10+01:00","package":"lu.cfl.app","title":"Train delayed","text":"Train 88576 delayed by 5 minutes","channel":"service_updates","id":"1001"}
```

Store this file on the device (e.g., `/sdcard/NOTIF/device_notifications.ndjson`).

To copy into a run folder:

```sh
python -m campaign.cli sync-device-notifs \
  --run-dir /sdcard/NOTIF/campaigns/RUN_20260205_080000__morning_peak \
  --device-ndjson /sdcard/NOTIF/device_notifications.ndjson
```

## Report (PC)

```sh
python -m campaign.cli report \
  --run-dir ./campaign_runs/RUN_20260205_080000__morning_peak \
  --device-ndjson ./device_notifications.ndjson \
  --match-threshold 70
```

Outputs:

- `report_summary.json`
- `matches.csv`
- `metrics_by_changeType.csv`
- `metrics_by_subscr.csv`
- `metrics_by_scenario.csv`
- `unmatched_events.csv`
- `unmatched_notifications.csv`
- `report.md` (optional)

## Notes

- API calls are rate limited via `pollSec` with backoff outside the window.
- Logs redact `aid`, `user_id`, and `channel_id` in saved request/response payloads.
- Matching uses `rapidfuzz` if available, otherwise a fallback string similarity.

