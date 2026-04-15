import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from .config import AppConfig
from .commands import run_configured_command
from .profile_actions import apply_audio_settings, apply_display_settings, profile_is_configured
from .rpi_client import RpiClient
from .steam import debug_visible_windows_for_title, find_big_picture_process_id, is_big_picture_running
from .windows import is_remote_session, show_desktop_notification


logger = logging.getLogger(__name__)


class RemoteSessionSwitchError(RuntimeError):
    pass


class GamingModeManager:
    def __init__(self, config: AppConfig):
        self.config = config
        self.rpi_client = RpiClient(config)
        self._lock = None
        self._active = False
        self._last_trigger = "startup"
        self._last_transition_at = None
        self._big_picture_pid: Optional[int] = None
        self._last_rpi_status: Optional[Dict] = None
        self._last_rpi_status_at: Optional[str] = None
        self._last_rpi_status_error: str = ""
        self._last_rpi_status_ok: Optional[bool] = None

    @property
    def active(self) -> bool:
        return self._active

    def _is_initial_setup_complete(self) -> bool:
        return bool(
            self.config.rpi_base_url.strip()
            and self.config.rpi_api_key.strip()
            and profile_is_configured(self.config.default_profile)
            and profile_is_configured(self.config.gaming_profile)
        )

    def status(self) -> Dict:
        return {
            "gaming_mode_active": self._active,
            "current_profile": "gaming" if self._active else "default",
            "last_trigger": self._last_trigger,
            "last_transition_at": self._last_transition_at,
            "initial_setup_complete": self._is_initial_setup_complete(),
            "remote_session_active": is_remote_session(),
            "rpi_configured": self.rpi_client.is_configured(),
            "rpi_host": self.rpi_client.get_host(),
            "rpi_last_status": self._last_rpi_status,
            "rpi_last_status_at": self._last_rpi_status_at,
            "rpi_last_status_error": self._last_rpi_status_error,
            "steam_big_picture_running": self._is_big_picture_running(),
            "steam_big_picture_pid": self._big_picture_pid,
            "profiles": {
                "default": {
                    "display": {
                        "topology": self.config.default_profile.display.topology,
                    },
                    "audio": {
                        "enabled": self.config.default_profile.audio.enabled,
                        "endpoint_id": self.config.default_profile.audio.endpoint_id,
                        "endpoint_name": self.config.default_profile.audio.endpoint_name,
                        "volume_scalar": self.config.default_profile.audio.volume_scalar,
                    },
                },
                "gaming": {
                    "display": {
                        "topology": self.config.gaming_profile.display.topology,
                    },
                    "audio": {
                        "enabled": self.config.gaming_profile.audio.enabled,
                        "endpoint_id": self.config.gaming_profile.audio.endpoint_id,
                        "endpoint_name": self.config.gaming_profile.audio.endpoint_name,
                        "volume_scalar": self.config.gaming_profile.audio.volume_scalar,
                    },
                },
            },
        }

    def _ensure_switch_allowed(self, trigger: str, action: str) -> None:
        if not is_remote_session():
            return

        message = (
            f"Refusing `{action}` because the current Windows session is running over Remote Desktop. "
            f"Display and audio switching must be triggered from a local session."
        )
        logger.warning("%s (trigger=%s)", message, trigger)
        raise RemoteSessionSwitchError(message)

    def _is_big_picture_running(self) -> bool:
        return is_big_picture_running(self.config.steam_window_title_contains)

    async def _capture_big_picture_pid(self) -> Optional[int]:
        pid = await asyncio.to_thread(find_big_picture_process_id, self.config.steam_window_title_contains)
        if pid:
            if self._big_picture_pid != pid:
                logger.info(
                    "Tracking Big Picture via window title match `%s` on PID %s",
                    self.config.steam_window_title_contains,
                    pid,
                )
            self._big_picture_pid = pid
        else:
            self._big_picture_pid = None
        return pid

    def _get_lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    async def enter(self, trigger: str) -> Dict:
        async with self._get_lock():
            steps: List[Dict] = []
            if self._active:
                return {
                    "ok": True,
                    "action": "switch_to_game_mode",
                    "gaming_mode_active": True,
                    "trigger": trigger,
                    "steps": [{"step": "enter", "skipped": True, "reason": "already_active"}],
                }

            self._ensure_switch_allowed(trigger, "switch_to_game_mode")
            self._big_picture_pid = None
            logger.info("Entering gaming mode (trigger=%s)", trigger)
            show_desktop_notification("Switcherino PC", "Switching to gaming mode...")
            try:
                steps.append(await self.rpi_client.post_action("switch_to_game_mode"))
            except Exception:
                if self.rpi_client.is_configured():
                    show_desktop_notification("Switcherino PC", "Could not contact switcherino-rpi.")
                raise
            steps.append(await apply_display_settings(self.config.gaming_profile.display, "display_enter"))
            steps.append(await apply_audio_settings(self.config.gaming_profile.audio, "audio_enter"))
            steps.append(await run_configured_command(self.config.launch_big_picture_command, "launch_big_picture"))
            await self._capture_big_picture_pid()

            self._active = True
            self._last_trigger = trigger
            self._last_transition_at = datetime.now(timezone.utc).isoformat()
            logger.info("Gaming mode entered successfully (trigger=%s)", trigger)
            return {
                "ok": True,
                "action": "switch_to_game_mode",
                "gaming_mode_active": True,
                "trigger": trigger,
                "steps": steps,
            }

    async def exit(self, trigger: str, request_big_picture_close: bool) -> Dict:
        async with self._get_lock():
            steps: List[Dict] = []
            self._ensure_switch_allowed(trigger, "switch_to_default_mode")
            logger.info("Leaving gaming mode (trigger=%s, request_big_picture_close=%s)", trigger, request_big_picture_close)
            show_desktop_notification("Switcherino PC", "Switching to default mode...")
            if request_big_picture_close:
                steps.append(await run_configured_command(self.config.exit_big_picture_command, "exit_big_picture"))
            else:
                steps.append({"step": "exit_big_picture", "skipped": True, "reason": "detected_already_closed"})

            steps.append(await self.rpi_client.post_action("switch_to_default_mode"))
            steps.append(await apply_display_settings(self.config.default_profile.display, "display_exit"))
            steps.append(await apply_audio_settings(self.config.default_profile.audio, "audio_exit"))

            self._active = False
            self._big_picture_pid = None
            self._last_trigger = trigger
            self._last_transition_at = datetime.now(timezone.utc).isoformat()
            logger.info("Gaming mode left successfully (trigger=%s)", trigger)
            return {
                "ok": True,
                "action": "switch_to_default_mode",
                "gaming_mode_active": False,
                "trigger": trigger,
                "steps": steps,
            }

    async def monitor_steam(self, stop_event: asyncio.Event) -> None:
        missing_polls = 0
        while not stop_event.is_set():
            try:
                if self._active:
                    current_transition_at = self._last_transition_at
                    running = await self._capture_big_picture_pid() is not None
                    if running:
                        missing_polls = 0
                    else:
                        within_launch_grace = False
                        if current_transition_at:
                            try:
                                launched_at = datetime.fromisoformat(current_transition_at)
                                within_launch_grace = (
                                    self._last_trigger in ("api", "tray", "controller_hold")
                                    and datetime.now(timezone.utc) - launched_at
                                    < timedelta(seconds=self.config.steam_launch_grace_seconds)
                                )
                            except ValueError:
                                within_launch_grace = False

                        if within_launch_grace:
                            await self._capture_big_picture_pid()
                            if self._is_big_picture_running():
                                missing_polls = 0
                                await asyncio.sleep(self.config.steam_poll_interval_seconds)
                                continue
                            missing_polls = 0
                        else:
                            missing_polls += 1
                            debug_snapshot = await asyncio.to_thread(
                                debug_visible_windows_for_title,
                                self.config.steam_window_title_contains,
                            )
                            logger.info(
                                "No visible Steam window matched `%s` (%s/%s). visible_window_count=%s matched_titles=%s",
                                self.config.steam_window_title_contains,
                                missing_polls,
                                max(1, int(self.config.steam_missing_polls_before_exit)),
                                debug_snapshot["visible_window_count"],
                                debug_snapshot["matched_titles"],
                            )

                        if missing_polls >= max(1, int(self.config.steam_missing_polls_before_exit)):
                            logger.info(
                                "No visible Steam window matched `%s` for %s consecutive polls, leaving gaming mode",
                                self.config.steam_window_title_contains,
                                missing_polls,
                            )
                            await self.exit("steam_exit", request_big_picture_close=False)
                            missing_polls = 0
                await asyncio.sleep(self.config.steam_poll_interval_seconds)
            except RemoteSessionSwitchError:
                missing_polls = 0
                await asyncio.sleep(self.config.steam_poll_interval_seconds)
            except Exception:
                logger.exception("Steam monitor loop crashed")
                await asyncio.sleep(self.config.steam_poll_interval_seconds)

    async def monitor_rpi_status(self, stop_event: asyncio.Event) -> None:
        interval_seconds = max(1.0, float(self.config.rpi_status_poll_interval_seconds))
        while not stop_event.is_set():
            try:
                if self.rpi_client.is_configured():
                    result = await self.rpi_client.get_status()
                    new_status = result.get("body")
                    request_ok = bool(result.get("ok"))
                    if request_ok != self._last_rpi_status_ok:
                        logger.info("RPi status request state changed: ok=%s", request_ok)
                        self._last_rpi_status_ok = request_ok
                    self._last_rpi_status = new_status
                    self._last_rpi_status_at = datetime.now(timezone.utc).isoformat()
                    self._last_rpi_status_error = ""
                else:
                    self._last_rpi_status = None
                    self._last_rpi_status_at = None
                    self._last_rpi_status_error = ""
                    self._last_rpi_status_ok = None
            except Exception as exc:
                if self._last_rpi_status_ok is not False:
                    logger.warning("RPi status request state changed: ok=False")
                self._last_rpi_status_ok = False
                self._last_rpi_status_error = str(exc)
                self._last_rpi_status_at = datetime.now(timezone.utc).isoformat()
                logger.warning("RPi status poll failed: %s", exc)

            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
            except asyncio.TimeoutError:
                continue
