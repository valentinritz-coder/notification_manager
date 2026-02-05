# Android (Termux) setup

## Install dependencies
```sh
pkg update
pkg install python git
pip install -r requirements.txt
```

## Filesystem permissions
```sh
termux-setup-storage
```

## Notification logging (external tool)
Use an external logger (Tasker/AutoNotification or similar) to append NDJSON lines to a path such as:
`/sdcard/NOTIF/device_notifications.ndjson`.

Each line should follow the example in `campaign/examples/device_notifications_example.ndjson`.

