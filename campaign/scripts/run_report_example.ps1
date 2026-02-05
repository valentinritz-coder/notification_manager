$RunDir = ".\campaign_runs\RUN_20260205_080000__morning_peak"
$DeviceNdjson = ".\device_notifications.ndjson"

python -m campaign.cli report `
  --run-dir $RunDir `
  --device-ndjson $DeviceNdjson `
  --match-threshold 70
