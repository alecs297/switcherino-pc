import logging
import os
import subprocess
import threading
from pathlib import Path
from urllib.parse import urlunsplit
import shlex

import pystray
from PIL import Image, ImageDraw

from .autostart import set_autostart_enabled
from .config import CONFIG_PATH, LOG_FILE, AppConfig, ensure_directories, load_config


logger = logging.getLogger(__name__)


def _open_path(path: Path) -> None:
    ensure_directories()
    if not path.exists():
        if path == CONFIG_PATH:
            load_config()
        else:
            path.touch()
    os.startfile(str(path))


def _run_optional_command(command: str) -> bool:
    text = str(command or "").strip()
    if not text:
        return False
    subprocess.Popen(shlex.split(text, posix=False))
    return True


def _local_docs_url(config: AppConfig) -> str:
    host = (config.host or "").strip() or "127.0.0.1"
    if host == "0.0.0.0":
        host = "127.0.0.1"
    return urlunsplit(("https", f"{host}:{config.port}", "/docs", "", ""))


def create_image() -> Image.Image:
    image = Image.new("RGBA", (64, 64), (28, 31, 38, 255))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((6, 6, 58, 58), radius=14, fill=(35, 157, 87, 255))
    draw.rectangle((18, 28, 46, 36), fill=(245, 245, 245, 255))
    draw.ellipse((24, 20, 40, 44), outline=(245, 245, 245, 255), width=4)
    return image


class TrayController:
    def __init__(self, config: AppConfig, runtime):
        self.config = config
        self.runtime = runtime
        self.icon = pystray.Icon("switcherino-pc", create_image(), "Switcherino PC")
        self.runtime.set_notifier(self.notify)

    def run(self) -> None:
        self._refresh_menu()
        self.icon.run()

    def stop(self) -> None:
        self.icon.stop()

    def notify(self, title: str, message: str) -> None:
        try:
            self.icon.notify(message, title)
        except Exception:
            logger.exception("Tray notification failed")

    def _refresh_menu(self) -> None:
        status = self.runtime.get_status_snapshot()
        self.icon.menu = pystray.Menu(
            pystray.MenuItem(lambda item: f"Program: {status['program']}", lambda icon, item: None, enabled=False),
            pystray.MenuItem(lambda item: f"Web Server: {status['web_server']}", lambda icon, item: None, enabled=False),
            pystray.MenuItem(
                lambda item: f"Server Error: {status['web_server_error'] or 'none'}",
                lambda icon, item: None,
                enabled=False,
            ),
            pystray.MenuItem(lambda item: f"Gaming Mode: {status['gaming_mode']}", lambda icon, item: None, enabled=False),
            pystray.MenuItem(lambda item: f"Controller Monitor: {status['controller_monitor']}", lambda icon, item: None, enabled=False),
            pystray.MenuItem(lambda item: f"Autostart: {status['autostart']}", lambda icon, item: None, enabled=False),
            pystray.MenuItem(lambda item: f"Initial Setup: {status['initial_setup']}", lambda icon, item: None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Gaming Mode On",
                self._enter_game_mode,
                enabled=lambda item: not self.runtime.is_game_mode_active(),
            ),
            pystray.MenuItem(
                "Gaming Mode Off",
                self._exit_game_mode,
                enabled=lambda item: self.runtime.is_game_mode_active(),
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Start with Windows",
                self._toggle_autostart,
                checked=lambda item: self.config.autostart_enabled,
            ),
            pystray.MenuItem("Restart Web Server", self._restart_server),
            pystray.MenuItem("Open API Docs", self._open_api_docs),
            pystray.MenuItem("Open Config File", self._open_config_file),
            pystray.MenuItem("Open Log File", self._open_log_file),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", self._quit),
        )
        self.icon.update_menu()

    def _toggle_autostart(self, icon, item) -> None:
        set_autostart_enabled(self.config, not self.config.autostart_enabled)
        self.notify("Switcherino PC", f"Autostart {'enabled' if self.config.autostart_enabled else 'disabled'}")
        self._refresh_menu()

    def _enter_game_mode(self, icon, item) -> None:
        try:
            self.runtime.enter_game_mode_from_tray()
            self.notify("Switcherino PC", "Gaming mode enabled")
        except Exception as exc:
            logger.exception("Failed to enable gaming mode from tray")
            self.notify("Switcherino PC", f"Unable to enable gaming mode: {exc}")
        self._refresh_menu()

    def _exit_game_mode(self, icon, item) -> None:
        try:
            self.runtime.exit_game_mode_from_tray()
            self.notify("Switcherino PC", "Gaming mode disabled")
        except Exception as exc:
            logger.exception("Failed to disable gaming mode from tray")
            self.notify("Switcherino PC", f"Unable to disable gaming mode: {exc}")
        self._refresh_menu()

    def _restart_server(self, icon, item) -> None:
        def worker() -> None:
            try:
                self.runtime.restart_server()
                self.config = self.runtime.config
                self.runtime.set_notifier(self.notify)
                self.notify("Switcherino PC", "Web server restarted")
            except Exception as exc:
                logger.exception("Failed to restart web server")
                self.notify("Switcherino PC", f"Unable to restart web server: {exc}")
            self._refresh_menu()

        threading.Thread(target=worker, daemon=True).start()

    def _open_api_docs(self, icon, item) -> None:
        os.startfile(_local_docs_url(self.config))

    def _open_config_file(self, icon, item) -> None:
        if not _run_optional_command(self.config.open_config_command):
            _open_path(CONFIG_PATH)

    def _open_log_file(self, icon, item) -> None:
        if not _run_optional_command(self.config.open_logs_command):
            _open_path(LOG_FILE)

    def _quit(self, icon, item) -> None:
        self.stop()
