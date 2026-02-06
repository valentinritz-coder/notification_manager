# HAFAS Notifications Campaign

This toolkit manages end-to-end notification campaigns for HAFAS subscriptions:

1. Define scenarios (`ctxRecon` + `serviceDays` + hysteresis).
2. Run a campaign on Android (Termux) to subscribe and poll for `rtEvents`.
3. Log device notifications externally (Tasker/AutoNotification) as NDJSON.
4. Generate a report on a PC to match events to notifications and compute metrics.

## Quickstart (Termux copy/paste)

Use this block as-is in Termux. `HAFAS_CLIENT_ID` maps to the request payload `client.id` (HAFAS/CFL enum) and **must not** be the Android `ANDROID-xxxx` push channel id.

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
  --aid "$HAFAS_AID" \
  --user-id "$HAFAS_USER_ID" \
  --channel-id "$HAFAS_CHANNEL_ID" \
  --client-id "$HAFAS_CLIENT_ID"
```

### Common mistakes

- Don’t put the ANDROID-xxxx push channel id into `--client-id`.
- `--hci-client-type` should be `AND` (not `ANDROID`).
- `--client-id` is the HAFAS/CFL client enum (e.g., `HAFAS`, `CFL`).

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
  "idleGraceMin": 15,
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

**Polling window behavior:** `preWindowMin`/`postWindowMin` define the “interesting” window that affects polling cadence and stop conditions. Event collection itself is no longer gated by the window, so `rt_events.ndjson` is written as soon as the API returns events—even if polling starts before the window or events arrive after the scheduled time.

## Running a campaign (Android)

Export credentials first to avoid leaking secrets in shell history:

```sh
export HAFAS_AID="..."
export HAFAS_USER_ID="..."
export HAFAS_CLIENT_ID="HAFAS"
export HAFAS_CHANNEL_ID="..."
```

`HAFAS_CLIENT_ID` is the HAFAS/CFL client enum used in the request envelope, while
`HAFAS_CHANNEL_ID` is the Android push channel id (ANDROID-xxxx) used for subscription delivery.

1. Subscribe:

```sh
cd ~/.../<repo>/campaign
python -m campaign.cli subscribe \
  --scenario ./examples/scenario_example.json \
  --out-root /sdcard/NOTIF/campaigns \
  --base-url "https://cfl.hafas.de/gate" \
  --aid "$HAFAS_AID" \
  --user-id "$HAFAS_USER_ID" \
  --client-id "$HAFAS_CLIENT_ID" \
  --channel-id "$HAFAS_CHANNEL_ID"
```

2. Poll (use the run dir printed by `subscribe`):

```sh
cd ~/.../<repo>/campaign
python -m campaign.cli poll \
  --run-dir /sdcard/NOTIF/campaigns/RUN_20260205_080000__morning_peak \
  --idle-grace-min 15 \
  --base-url "https://cfl.hafas.de/gate" \
  --aid "$HAFAS_AID" \
  --user-id "$HAFAS_USER_ID" \
  --client-id "$HAFAS_CLIENT_ID" \
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

### Free notification logging via Notification Log export

If you want a free logger, install the Android app **Notification Log** (`org.hcilab.projects.nlog`). It can export all posted/removed notifications to a single JSON file.

**Export flow (Notification Log app):**
1. Open the app, choose **Export**, and save the JSON to a shared folder (e.g. `/sdcard/NOTIF/notification_log_export.json`).
2. Convert the export JSON into our NDJSON format:

```sh
python -m campaign.cli import-notification-log \
  --export-json /sdcard/NOTIF/notification_log_export.json \
  --out-ndjson /sdcard/NOTIF/device_notifications.ndjson \
  --append \
  --packages de.hafas.android.cfl,lu.cfl.cflgo.qual
```

**Run-folder flow (recommended):**

```sh
python -m campaign.cli import-notification-log \
  --export-json /sdcard/NOTIF/notification_log_export.json \
  --run-dir /sdcard/NOTIF/campaigns/RUN_20260205_080000__morning_peak \
  --packages de.hafas.android.cfl
```

Recommended CFL app filters:
- `de.hafas.android.cfl` (CFL mobile)
- `lu.cfl.cflgo.qual` (CFL GO QUAL)

**Recommended pipeline:**
1. Subscribe (`campaign.cli subscribe`)
2. Poll (`campaign.cli poll`)
3. Export notifications JSON from Notification Log
4. Import into `run-dir/device/notifications.ndjson` (`campaign.cli import-notification-log`)
5. Report (`campaign.cli report`)

**Storage convention (Termux):**
- Repo and venv in `~`
- Outputs in `/sdcard/NOTIF`
- Remember to run `termux-setup-storage` once

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
- Polling stops per subscription once the planned arrival window ends and no new RT activity
  has been observed for `idleGraceMin` minutes.
- Logs redact `aid`, `user_id`, and `channel_id` in saved request/response payloads.
- Matching uses `rapidfuzz` if available, otherwise a fallback string similarity.
- Notification `id` is a stable identifier for update detection, not a global event id.
  - `nid`: Android notification ID (int) used by the app to update/replace notifications.
  - `key`: unique-ish notification key string that may include user/profile and tag; also used to detect updates.
  - Reports can count either per `id` (latest state) or treat each `postTime` as a new event depending on strategy.
- Notification Log exports may have an empty `removed[]` unless removal tracking is enabled in the app settings.
