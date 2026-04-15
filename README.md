# switcherino-pc

Utility for controlling a local Windows gaming-mode workflow while coordinating with [`switcherino-rpi`](https://github.com/alecs297/switcherino-rpi).

The main objective is to let a Windows PC expose a small local HTTPS API, react to controller shortcuts, switch local display and audio profiles, launch Steam Big Picture, and keep that in sync with the Raspberry Pi bridge that controls the TV side.

## What This Project Does

This project turns a Windows PC into a small control bridge for local gaming mode:

- the PC runs a local HTTPS API
- the API uses Bearer-token authentication
- the app can start automatically when the user logs in
- the app monitors connected controllers
- holding the Xbox / PS home button for 3 seconds can trigger gaming mode
- gaming mode can also be triggered through the local API
- entering gaming mode can call the Raspberry Pi API, switch the local display topology, switch the local default audio device and volume, and launch Steam Big Picture
- when Big Picture exits, the app can roll everything back automatically

The Raspberry Pi remains responsible for the TV-side behavior. This project only handles the PC-side behavior.

## Setup Model

The setup is:

- the Raspberry Pi runs `switcherino-rpi`
- the Windows PC runs `switcherino-pc`
- the PC asks the Pi to enter or leave gaming mode
- the Pi switches the TV side
- the PC switches its own local display and audio side

Typical flow:

1. hold the controller home button for 3 seconds, or call `POST /pc/action`
2. the PC calls the Pi to enter gaming mode
3. the PC applies the configured `gaming_profile`
4. the PC launches Steam Big Picture
5. when Big Picture exits, the PC applies the configured `default_profile` and calls the Pi to return to default mode

## Delivery Model

The recommended delivery format is a Windows `.exe` built with `PyInstaller`.

During development, the app can still be run directly with Python.

The packaged app is designed to run in the background with a tray icon that allows you to:

- view the current runtime status
- enable or disable gaming mode manually
- restart the local web server
- enable or disable autostart
- open the config file
- open the log file
- quit the app cleanly

## Installation

### 1 - Create a virtual environment and install dependencies

```powershell
python -m venv venv
venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

### 2 - Create the initial config

Run:

```powershell
scripts\initial-setup.ps1
```

This will:

- create the config file if it does not exist yet
- ask for the Raspberry Pi base URL
- ask for the Raspberry Pi API key
- optionally fetch `/certs` from the Raspberry Pi automatically
- save the Pi certificate PEM locally when available
- offer to launch the interactive display and audio profile helper
- open the config file at the end if you want to review it manually

The display and audio helper can also be run directly later:

```powershell
scripts\display-helper.ps1
```

That helper:

- asks whether audio should be captured too
- captures a `default_profile`
- captures a `gaming_profile`
- stores the chosen display topology for each profile
- stores the current default render endpoint and volume when audio capture is enabled

You can also start the app directly once:

```powershell
python app.py
```

On first start, the app creates its config and self-signed certificate files automatically.

### 3 - Review the generated config

The config file is stored in:

```text
%LOCALAPPDATA%\SwitcherinoPc\config.json
```

The most important fields are:

```json
{
  "host": "0.0.0.0",
  "port": 8443,
  "api_key": "generated-secret",
  "cert_file": "C:\\Users\\Alice\\AppData\\Local\\SwitcherinoPc\\certs\\server.crt",
  "key_file": "C:\\Users\\Alice\\AppData\\Local\\SwitcherinoPc\\certs\\server.key",
  "suggested_base_url": "https://127.0.0.1:8443",
  "rpi_base_url": "https://192.168.1.20:8443",
  "rpi_api_key": "pi-secret",
  "rpi_verify_tls": true,
  "rpi_ca_file": "",
  "rpi_cert_fingerprint": "",
  "rpi_status_poll_interval_seconds": 30.0,
  "controller_backend": "pygame",
  "controller_poll_interval_seconds": 0.05,
  "home_button_hold_seconds": 3.0,
  "require_quiet_controller_hold": true,
  "analog_deadzone": 0.35,
  "controller_profiles": [
    {
      "name_contains": "Xbox",
      "home_button_indices": [5]
    },
    {
      "name_contains": "DualSense",
      "home_button_indices": [5]
    },
    {
      "name_contains": "Wireless Controller",
      "home_button_indices": [5]
    }
  ],
  "default_profile": {
    "display": {
      "topology": "internal_only"
    },
    "audio": {
      "enabled": false,
      "endpoint_id": "",
      "endpoint_name": "",
      "volume_scalar": null
    }
  },
  "gaming_profile": {
    "display": {
      "topology": "external_only"
    },
    "audio": {
      "enabled": true,
      "endpoint_id": "{0.0.0.00000000}.{example-id}",
      "endpoint_name": "LG TV",
      "volume_scalar": 0.42
    }
  },
  "launch_big_picture_command": "cmd /c start \"\" \"steam://open/bigpicture\"",
  "exit_big_picture_command": "cmd /c start \"\" \"steam://close/bigpicture\"",
  "steam_window_title_contains": "Big Picture",
  "steam_launch_grace_seconds": 10.0,
  "steam_poll_interval_seconds": 2.0,
  "steam_missing_polls_before_exit": 3,
  "autostart_enabled": false,
  "autostart_command": "",
  "tray_enabled": true,
  "open_logs_command": "",
  "open_config_command": "",
  "log_level": "INFO"
}
```

Configuration reference:

| Key | Purpose |
| --- | --- |
| `host` | Bind address for the local FastAPI server |
| `port` | HTTPS port exposed by the local API |
| `api_key` | Bearer token used to authenticate local protected endpoints |
| `cert_file` | Local TLS certificate path used by the HTTPS server |
| `key_file` | Local TLS private key path used by the HTTPS server |
| `suggested_base_url` | Base URL advertised by `/certs` for local clients |
| `rpi_base_url` | Base URL of the Raspberry Pi bridge |
| `rpi_api_key` | Bearer token used when calling the Raspberry Pi |
| `rpi_verify_tls` | Whether the PC verifies the Pi TLS certificate |
| `rpi_ca_file` | Optional CA or server certificate file for trusting the Pi |
| `rpi_cert_fingerprint` | Optional SHA-256 fingerprint pin for the Pi certificate |
| `rpi_status_poll_interval_seconds` | Poll interval used for refreshing cached Raspberry Pi status |
| `controller_backend` | Controller backend selection. V1 currently supports `pygame` |
| `controller_poll_interval_seconds` | Sleep interval used by the controller monitor loop |
| `home_button_hold_seconds` | Duration the controller home button must stay pressed before triggering gaming mode |
| `require_quiet_controller_hold` | Reserved config flag for quiet-hold behavior. In the current implementation, other controller activity still cancels the trigger |
| `analog_deadzone` | Minimum analog axis movement considered meaningful controller activity |
| `controller_profiles` | Controller name matching and home-button mapping used by the controller monitor |
| `default_profile.display.topology` | Display topology used when returning to the normal PC state |
| `default_profile.audio.enabled` | Whether the default profile restores audio |
| `default_profile.audio.endpoint_id` | Windows endpoint ID used when returning to the default profile |
| `default_profile.audio.endpoint_name` | Friendly endpoint name saved for review and logs |
| `default_profile.audio.volume_scalar` | Volume restored for the default profile, from `0.0` to `1.0` |
| `gaming_profile.display.topology` | Display topology used when entering the gaming state |
| `gaming_profile.audio.enabled` | Whether the gaming profile restores audio |
| `gaming_profile.audio.endpoint_id` | Windows endpoint ID used when entering the gaming profile |
| `gaming_profile.audio.endpoint_name` | Friendly endpoint name saved for review and logs |
| `gaming_profile.audio.volume_scalar` | Volume restored for the gaming profile, from `0.0` to `1.0` |
| `launch_big_picture_command` | Command used to launch Steam Big Picture |
| `exit_big_picture_command` | Command used to request Big Picture exit |
| `steam_window_title_contains` | Window title fragment used to detect whether Big Picture is still running |
| `steam_launch_grace_seconds` | Grace period after launching Big Picture before rollback detection is allowed |
| `steam_poll_interval_seconds` | Poll interval used to detect whether Big Picture is still visible |
| `steam_missing_polls_before_exit` | Number of consecutive failed Big Picture polls before rollback is triggered |
| `autostart_enabled` | Enables autostart for the current user |
| `autostart_command` | Optional custom autostart command |
| `tray_enabled` | Enables the tray icon UI |
| `open_logs_command` | Optional custom command used by the tray to open the log location |
| `open_config_command` | Optional custom command used by the tray to open the config location |
| `log_level` | Logging verbosity passed to the web server runtime |

Each profile contains:

- `display.topology`
- `audio.enabled`
- `audio.endpoint_id`
- `audio.endpoint_name`
- `audio.volume_scalar`

Each `controller_profiles` entry contains:

- `name_contains`
- `home_button_indices`

Minimum setup for a useful first run:

- `rpi_base_url`
- `rpi_api_key`
- `default_profile.display.topology`
- `gaming_profile.display.topology`

You can also leave the Raspberry Pi fields blank during the initial setup if you want to start with an empty config and fill it manually later.

Important setup notes:

- V1 display switching is topology-based and uses the same `DisplaySwitch` model as `Win+P`
- supported topologies are `internal_only`, `external_only`, `clone`, and `extend`
- audio capture stores the current default render endpoint and the current volume

Recommended capture flow:

1. run `scripts\display-helper.ps1`
2. put Windows in the desired default state
3. capture `default_profile`
4. put Windows in the desired gaming state
5. capture `gaming_profile`

## Certificates

The app generates a self-signed certificate automatically for the local HTTPS server.

Generated files are stored in:

```text
%LOCALAPPDATA%\SwitcherinoPc\certs
```

Clients can retrieve certificate pinning information from:

- `GET /certs`

## Logging

Logs are written to:

```text
%LOCALAPPDATA%\SwitcherinoPc\logs\switcherino-pc.log
```

If startup fails, the app also shows a Windows message box pointing to the config and log paths.


## Autostart Strategy

The V1 autostart strategy is implemented through a Windows registry key under `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`.

This makes autostart easy to enable or disable, and does not require administrator rights, but it does not run before login.

If a future version needs pre-login startup, that would require a different model such as Task Scheduler or a Windows service.

## Controller Behavior

The app currently monitors controllers through `pygame`.

Target behavior:

- Xbox controllers
- DualSense controllers
- holding the home button for 3 seconds enters gaming mode
- other controller activity during the hold cancels the trigger

Important controller note:

- home-button indexing can vary depending on the controller, driver, and SDL mapping on Windows
- the default project config currently uses button `5` as the validated home-button index for both Xbox and PlayStation controllers on this setup
- you should expect to validate the configured home-button indices on your own hardware
- the default config accepts multiple candidate home-button indices per controller profile when mappings vary

## Debug Scripts

Useful scripts in [`scripts`](C:\Users\Alex\Desktop\coding\switcherino-pc\scripts):

- `scripts\debug-controller.py`: prints detected controllers, button events, axis and hat movement, and reports a long press after the configured hold duration. Use it to validate the real `PS/Xbox` button index on the current machine.
- `scripts\inspect-steam.py`: watches visible Windows titles to help debug Steam / Big Picture detection and rollback behavior.

Controller debug example:

```powershell
python scripts\debug-controller.py
```

Useful options:

- `--hold-seconds 3` to change the long-press threshold during tests
- `--deadzone 0.35` to adjust how much analog movement is logged
- `--poll-sleep 0.02` to change the polling cadence

## API Behavior

Swagger documentation is exposed locally through FastAPI at:

- `/docs`
- `/redoc`

Main local API routes:

- `GET /certs`
- `GET /pc/status`
- `POST /pc/action`

Protected endpoints use:

```text
Authorization: Bearer YOUR_API_KEY
```

### `GET /pc/status`

Returns the current bridge status, including:

- whether gaming mode is active
- which local profile is currently active
- whether Windows currently reports a Remote Desktop session
- whether the Raspberry Pi is configured
- the Raspberry Pi host
- whether Steam Big Picture is currently detected
- controller monitor state
- the configured `default` and `gaming` profiles, including structured display and audio settings
- whether the initial setup looks complete

### `POST /pc/action`

Supported actions:

- `switch_to_game_mode`
- `switch_to_default_mode`

For schema compatibility, the request model also accepts:

- `turn_on`
- `turn_off`
- `change_source`

Those actions are intentionally rejected with `400` on the PC bridge.

Example request:

```powershell
curl.exe -k `
  -H "Authorization: Bearer YOUR_API_KEY" `
  -H "Content-Type: application/json" `
  -d "{\"action\":\"switch_to_game_mode\"}" `
  https://127.0.0.1:8443/pc/action
```

**Note** : if Windows reports that the current session is running over Remote Desktop, `switch_to_game_mode` and `switch_to_default_mode` are rejected : the API returns `409 Conflict` in that case

## Runtime Behavior

Entering gaming mode currently does the following:

1. call the Raspberry Pi with `switch_to_game_mode`
2. apply `gaming_profile.display.topology`
3. optionally restore `gaming_profile.audio.endpoint_id` and `gaming_profile.audio.volume_scalar`
4. launch Steam Big Picture

Leaving gaming mode currently does the following:

1. request Big Picture exit, unless it is already gone
2. call the Raspberry Pi with `switch_to_default_mode`
3. apply `default_profile.display.topology`
4. optionally restore `default_profile.audio.endpoint_id` and `default_profile.audio.volume_scalar`

Automatic rollback:

- when Big Picture is no longer detected for several consecutive polls, the app leaves gaming mode automatically

## Building the Executable

Install build dependencies:

```powershell
python -m pip install -r requirements.txt -r requirements-build.txt
```

Build:

```powershell
scripts\build.ps1
```

Generated binary:

```text
dist\switcherino-pc.exe
```

## Current Limitations

- display switching is intentionally limited to the four Windows projection-style topologies for V1
- V1 does not try to restore a full monitor layout including refresh rate, HDR, resolution, scaling, or exact screen identities
- controller home-button mapping still needs real hardware validation
