# Android (Termux) setup

## Install dependencies
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

## Filesystem permissions
```sh
termux-setup-storage
```

Only needed because outputs are written to `/sdcard/NOTIF`. Keep the repo and venv in `~`.

## Notification logging (external tool)
Use an external logger (Tasker/AutoNotification or similar) to append NDJSON lines to a path such as:
`/sdcard/NOTIF/device_notifications.ndjson`.

Each line should follow the example in `campaign/examples/device_notifications_example.ndjson`.
