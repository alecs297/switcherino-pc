import asyncio
import logging
import threading
from typing import Optional

import uvicorn

from .app import create_app
from .certs import ensure_self_signed_cert
from .config import AppConfig, load_config


logger = logging.getLogger(__name__)


class AppRuntime:
    def __init__(self, config: AppConfig):
        self.config = config
        self.app = None
        self.server: Optional[uvicorn.Server] = None
        self.server_thread: Optional[threading.Thread] = None
        self.started_event = threading.Event()
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self._lock = threading.RLock()
        self.last_server_error: Optional[str] = None

    def start(self) -> None:
        with self._lock:
            self.started_event = threading.Event()
            self.last_server_error = None
            ensure_self_signed_cert(self.config.cert_file, self.config.key_file)
            self.app = create_app(self.config)

            def run_server() -> None:
                try:
                    logger.info(
                        "Starting web server on https://%s:%s",
                        self.config.host,
                        self.config.port,
                    )
                    asyncio.set_event_loop(asyncio.new_event_loop())
                    self.loop = asyncio.get_event_loop()
                    config = uvicorn.Config(
                        self.app,
                        host=self.config.host,
                        port=self.config.port,
                        ssl_certfile=self.config.cert_file,
                        ssl_keyfile=self.config.key_file,
                        log_level=self.config.log_level.lower(),
                        log_config=None,
                        access_log=False,
                    )
                    self.server = uvicorn.Server(config)
                    self.server.run()
                    logger.info("Web server thread exited")
                except Exception as exc:
                    self.last_server_error = str(exc)
                    logger.exception("Web server crashed during startup or runtime")
                finally:
                    self.server = None
                    self.loop = None
                    self.started_event.set()

            self.server_thread = threading.Thread(target=run_server, name="uvicorn-server", daemon=True)
            self.server_thread.start()

            deadline = threading.Event()
            for _ in range(100):
                if self.server is not None and getattr(self.server, "started", False):
                    logger.info("Web server is accepting connections")
                    self.started_event.set()
                    break
                if self.server_thread is not None and not self.server_thread.is_alive():
                    break
                deadline.wait(0.1)

            self.started_event.wait(timeout=1.0)
            if self.last_server_error:
                logger.error("Web server failed to start: %s", self.last_server_error)
            elif self.server is None or not getattr(self.server, "started", False):
                logger.warning("Web server did not report a successful startup")

    def stop(self) -> None:
        with self._lock:
            if self.server is not None:
                logger.info("Stopping web server")
                self.server.should_exit = True
            if self.server_thread is not None and self.server_thread.is_alive():
                self.server_thread.join(timeout=10.0)
            self.server_thread = None

    def is_server_running(self) -> bool:
        return (
            self.server_thread is not None
            and self.server_thread.is_alive()
            and self.server is not None
            and getattr(self.server, "started", False)
        )

    def is_game_mode_active(self) -> bool:
        if self.app is None or not hasattr(self.app.state, "manager"):
            return False
        return bool(self.app.state.manager.active)

    def _run_manager_action(self, method_name: str, trigger: str):
        if self.loop is None or self.app is None or not hasattr(self.app.state, "manager"):
            raise RuntimeError("Server loop is not ready")
        manager = self.app.state.manager
        if method_name == "enter":
            coro = manager.enter(trigger)
        else:
            coro = manager.exit(trigger, True)
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout=30.0)

    def enter_game_mode_from_tray(self):
        return self._run_manager_action("enter", "tray")

    def exit_game_mode_from_tray(self):
        return self._run_manager_action("exit", "tray")

    def restart_server(self) -> None:
        with self._lock:
            self.stop()
            self.config = load_config()
            self.start()

    def get_status_snapshot(self) -> dict:
        manager = getattr(getattr(self.app, "state", None), "manager", None)
        controller = getattr(getattr(self.app, "state", None), "controller", None)
        return {
            "program": "running",
            "web_server": "running" if self.is_server_running() else "stopped",
            "web_server_error": self.last_server_error or "",
            "gaming_mode": "active" if manager and manager.active else "inactive",
            "controller_monitor": "running" if controller and controller.running else "stopped",
            "autostart": "enabled" if self.config.autostart_enabled else "disabled",
            "initial_setup": "complete" if manager and manager.status().get("initial_setup_complete") else "incomplete",
        }
