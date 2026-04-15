import json
import os
import secrets
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import List, Optional


APP_NAME = "switcherino-pc"
APP_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("LOCALAPPDATA", APP_DIR / ".local")) / "SwitcherinoPc"
CONFIG_PATH = DATA_DIR / "config.json"
CERTS_DIR = DATA_DIR / "certs"
LOG_DIR = DATA_DIR / "logs"
LOG_FILE = LOG_DIR / "switcherino-pc.log"


@dataclass
class ControllerProfile:
    name_contains: str
    home_button_indices: List[int]


@dataclass
class DisplaySettings:
    topology: str = ""


@dataclass
class AudioSettings:
    enabled: bool = False
    endpoint_id: str = ""
    endpoint_name: str = ""
    volume_scalar: Optional[float] = None


@dataclass
class ModeProfile:
    display: DisplaySettings = field(default_factory=DisplaySettings)
    audio: AudioSettings = field(default_factory=AudioSettings)


@dataclass
class AppConfig:
    host: str = "0.0.0.0"
    port: int = 8443
    api_key: str = field(default_factory=lambda: secrets.token_hex(32))
    cert_file: str = ""
    key_file: str = ""
    suggested_base_url: str = "https://127.0.0.1:8443"
    rpi_base_url: str = ""
    rpi_api_key: str = ""
    rpi_verify_tls: bool = True
    rpi_ca_file: str = ""
    rpi_cert_fingerprint: str = ""
    rpi_status_poll_interval_seconds: float = 30.0
    controller_backend: str = "pygame"
    controller_poll_interval_seconds: float = 0.05
    home_button_hold_seconds: float = 3.0
    require_quiet_controller_hold: bool = True
    analog_deadzone: float = 0.35
    controller_profiles: List[ControllerProfile] = field(
        default_factory=lambda: [
            ControllerProfile(name_contains="Xbox", home_button_indices=[5]),
            ControllerProfile(name_contains="DualSense", home_button_indices=[5]),
            ControllerProfile(name_contains="Wireless Controller", home_button_indices=[5]),
        ]
    )
    default_profile: ModeProfile = field(default_factory=ModeProfile)
    gaming_profile: ModeProfile = field(default_factory=ModeProfile)
    launch_big_picture_command: str = 'cmd /c start "" "steam://open/bigpicture"'
    exit_big_picture_command: str = 'cmd /c start "" "steam://close/bigpicture"'
    steam_window_title_contains: str = "Big Picture"
    steam_launch_grace_seconds: float = 5.0
    steam_poll_interval_seconds: float = 3.0
    steam_missing_polls_before_exit: int = 2
    autostart_enabled: bool = False
    autostart_command: str = ""
    tray_enabled: bool = True
    open_logs_command: str = ""
    open_config_command: str = ""
    log_level: str = "INFO"


def ensure_directories() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CERTS_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def _default_config() -> AppConfig:
    config = AppConfig()
    config.cert_file = str(CERTS_DIR / "server.crt")
    config.key_file = str(CERTS_DIR / "server.key")
    config.default_profile = ModeProfile()
    config.gaming_profile = ModeProfile()
    return config


def _serialize(config: AppConfig) -> dict:
    data = asdict(config)
    data["controller_profiles"] = [asdict(profile) for profile in config.controller_profiles]
    data["default_profile"] = asdict(config.default_profile)
    data["gaming_profile"] = asdict(config.gaming_profile)
    return data


def write_default_config(path: Path = CONFIG_PATH) -> AppConfig:
    ensure_directories()
    config = _default_config()
    path.write_text(json.dumps(_serialize(config), indent=2), encoding="utf-8")
    return config


def _parse_controller_profiles(items: list) -> List[ControllerProfile]:
    profiles = []
    for item in items or []:
        raw_indices = item.get("home_button_indices")
        if isinstance(raw_indices, list):
            indices = []
            for value in raw_indices:
                try:
                    index = int(value)
                except (TypeError, ValueError):
                    continue
                if index >= 0 and index not in indices:
                    indices.append(index)
        else:
            try:
                legacy_index = int(item.get("home_button_index", -1))
            except (TypeError, ValueError):
                legacy_index = -1
            indices = [legacy_index] if legacy_index >= 0 else []

        profiles.append(
            ControllerProfile(
                name_contains=str(item.get("name_contains", "")).strip(),
                home_button_indices=indices,
            )
        )
    return [profile for profile in profiles if profile.name_contains and profile.home_button_indices]


def _normalize_display_topology(value: str) -> str:
    text = str(value or "").strip().lower()
    aliases = {
        "internal": "internal_only",
        "internal_only": "internal_only",
        "pc_screen_only": "internal_only",
        "external": "external_only",
        "external_only": "external_only",
        "second_screen_only": "external_only",
        "clone": "clone",
        "duplicate": "clone",
        "extend": "extend",
    }
    return aliases.get(text, text)


def _parse_display_settings(raw: Optional[dict], default: DisplaySettings) -> DisplaySettings:
    if not isinstance(raw, dict):
        return default
    topology = _normalize_display_topology(raw.get("topology", default.topology))
    return DisplaySettings(
        topology=topology,
    )


def _parse_audio_settings(raw: Optional[dict], default: AudioSettings) -> AudioSettings:
    if not isinstance(raw, dict):
        return default

    volume_scalar = raw.get("volume_scalar", default.volume_scalar)
    try:
        normalized_volume = None if volume_scalar in ("", None) else float(volume_scalar)
    except (TypeError, ValueError):
        normalized_volume = default.volume_scalar

    return AudioSettings(
        enabled=bool(raw.get("enabled", default.enabled)),
        endpoint_id=str(raw.get("endpoint_id", default.endpoint_id) or ""),
        endpoint_name=str(raw.get("endpoint_name", default.endpoint_name) or ""),
        volume_scalar=normalized_volume,
    )


def _parse_mode_profile(raw: Optional[dict], default: ModeProfile) -> ModeProfile:
    if not isinstance(raw, dict):
        return default
    return ModeProfile(
        display=_parse_display_settings(raw.get("display"), default.display),
        audio=_parse_audio_settings(raw.get("audio"), default.audio),
    )

def load_config(path: Path = CONFIG_PATH) -> AppConfig:
    ensure_directories()
    if not path.exists():
        return write_default_config(path)

    raw = json.loads(path.read_text(encoding="utf-8-sig"))
    defaults = _default_config()

    # Migrate the previous default hold duration to the new validated default.
    # If the user explicitly chose another value, keep it untouched.
    try:
        if float(raw.get("home_button_hold_seconds", defaults.home_button_hold_seconds)) == 5.0:
            raw["home_button_hold_seconds"] = defaults.home_button_hold_seconds
    except (TypeError, ValueError):
        raw["home_button_hold_seconds"] = defaults.home_button_hold_seconds

    raw["controller_profiles"] = _parse_controller_profiles(raw.get("controller_profiles", [])) or defaults.controller_profiles
    raw["default_profile"] = _parse_mode_profile(raw.get("default_profile"), defaults.default_profile)
    raw["gaming_profile"] = _parse_mode_profile(raw.get("gaming_profile"), defaults.gaming_profile)

    values = {}
    for field_name in defaults.__dataclass_fields__.keys():
        values[field_name] = raw.get(field_name, getattr(defaults, field_name))

    config = AppConfig(**values)
    if not config.cert_file:
        config.cert_file = defaults.cert_file
    if not config.key_file:
        config.key_file = defaults.key_file
    if not config.api_key:
        config.api_key = defaults.api_key
    normalized = _serialize(config)
    persisted = json.loads(path.read_text(encoding="utf-8-sig"))
    if normalized != persisted:
        save_config(config, path)
    return config


def save_config(config: AppConfig, path: Path = CONFIG_PATH) -> None:
    ensure_directories()
    path.write_text(json.dumps(_serialize(config), indent=2), encoding="utf-8")


def resolve_ca_file(path_value: str) -> Optional[str]:
    candidate = str(path_value or "").strip()
    return candidate or None
