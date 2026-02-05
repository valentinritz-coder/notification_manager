#!/data/data/com.termux/files/usr/bin/sh
set -e

SCENARIO_PATH=../examples/scenario_example.json
OUT_ROOT=/sdcard/NOTIF/campaigns
BASE_URL="https://www.cfl.lu/gate"

python -m campaign.cli subscribe \
  --scenario "$SCENARIO_PATH" \
  --out-root "$OUT_ROOT" \
  --base-url "$BASE_URL" \
  --aid "YOUR_AID" \
  --user-id "YOUR_USER_ID" \
  --channel-id "YOUR_CHANNEL_ID"

# Poll using the run dir printed from subscribe
# python -m campaign.cli poll --run-dir /sdcard/NOTIF/campaigns/RUN_... --base-url "$BASE_URL" --aid "YOUR_AID" --user-id "YOUR_USER_ID" --channel-id "YOUR_CHANNEL_ID"
