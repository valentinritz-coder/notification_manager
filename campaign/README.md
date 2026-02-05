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
cd ~/.../<repo>/campaign
mkdir -p ~/.venvs
python -m venv ~/.venvs/hafas_campaign
source ~/.venvs/hafas_campaign/bin/activate
pip install -r requirements.txt
pip install -e .
python -c "import campaign; print('campaign import OK:', campaign.__file__)"
```

**Quick workaround (no install, from the repo root):**

```sh
export PYTHONPATH="$PWD/src"
python -m campaign.cli --help
```

### How to get the repo on Android (Termux)

Termux home is under `~/` (not `/sdcard` by default). Keep the repo and virtualenv in `~/` so tools and Python packages are not on shared storage. Outputs are written to `/sdcard/NOTIF` for easy sharing/copying.

**Option A — git clone (recommended for updates):**

```sh
pkg install git
cd ~
git clone <REPO_URL>
```

**Option B — download ZIP and extract:**

```sh
pkg install curl unzip
cd ~
curl -L -o repo.zip <ZIP_URL>
unzip repo.zip
```

**Sync changes:**
- If using git: `git pull`
- If using ZIP: re-download and extract the latest archive.

### Termux storage permission (required for /sdcard output)

Before writing outputs to `/sdcard/NOTIF`, run:

```sh
termux-setup-storage
```

This grants Termux access to shared storage. Your code and venv stay in `~`.

### Recommended layout

```
Repo:    ~/.../<repo>/campaign
Venv:    ~/.venvs/hafas_campaign
Outputs: /sdcard/NOTIF/campaigns/...
```

Optional convenience command:

```sh
source ~/.venvs/hafas_campaign/bin/activate
```

## Install (PC)

```sh
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install -e .
python -c "import campaign; print('campaign import OK:', campaign.__file__)"
```

**Quick workaround (no install):**

```sh
export PYTHONPATH="$PWD/src"
python -m campaign.cli --help
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

Export credentials first to avoid leaking secrets in shell history:

```sh
export HAFAS_AID="..."
export HAFAS_USER_ID="..."
export HAFAS_CHANNEL_ID="..."
```

1. Subscribe:

```sh
cd ~/.../<repo>/campaign
python -m campaign.cli subscribe \
  --scenario ./examples/scenario_example.json \
  --out-root /sdcard/NOTIF/campaigns \
  --base-url "https://cfl.hafas.de/gate" \
  --aid "$HAFAS_AID" \
  --user-id "$HAFAS_USER_ID" \
  --channel-id "$HAFAS_CHANNEL_ID"
```

2. Poll (use the run dir printed by `subscribe`):

```sh
cd ~/.../<repo>/campaign
python -m campaign.cli poll \
  --run-dir /sdcard/NOTIF/campaigns/RUN_20260205_080000__morning_peak \
  --base-url "https://cfl.hafas.de/gate" \
  --aid "$HAFAS_AID" \
  --user-id "$HAFAS_USER_ID" \
  --channel-id "$HAFAS_CHANNEL_ID"
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

Device notifications can be provided either by:
- Passing `--device-ndjson` directly, **or**
- Running `sync-device-notifs` so the run folder contains `device/notifications.ndjson` (used automatically when `--device-ndjson` is omitted).

```sh
python -m campaign.cli report \
  --run-dir ./campaign_runs/RUN_20260205_080000__morning_peak \
  --match-threshold 70
```

Or with a direct path:

```sh
python -m campaign.cli report \
  --run-dir ./campaign_runs/RUN_20260205_080000__morning_peak \
  --device-ndjson ./device_notifications.ndjson \
  --match-threshold 70
```

**Quick workaround (no install):**

```sh
export PYTHONPATH="$PWD/src"
python -m campaign.cli report --run-dir ./campaign_runs/RUN_20260205_080000__morning_peak
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
