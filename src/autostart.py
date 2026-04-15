import logging
import sys
import winreg
from pathlib import Path

from .config import APP_NAME, AppConfig, save_config


logger = logging.getLogger(__name__)
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _default_command() -> str:
    app_path = Path(__file__).resolve().parent.parent / "app.py"
    return f'"{sys.executable}" "{app_path}"'


def sync_autostart(config: AppConfig) -> None:
    command = (config.autostart_command or "").strip() or _default_command()

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_ALL_ACCESS) as key:
        if config.autostart_enabled:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, command)
            logger.info("Autostart enabled with command: %s", command)
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
                logger.info("Autostart entry removed")
            except FileNotFoundError:
                logger.info("Autostart already disabled")


def set_autostart_enabled(config: AppConfig, enabled: bool) -> None:
    config.autostart_enabled = enabled
    save_config(config)
    sync_autostart(config)
