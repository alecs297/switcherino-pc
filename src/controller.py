import asyncio
import logging
import threading
import time
from typing import Callable, Dict, Optional

from .config import AppConfig, ControllerProfile


logger = logging.getLogger(__name__)


class ControllerMonitor:
    def __init__(self, config: AppConfig, trigger_callback: Callable[[str], asyncio.Future]):
        self.config = config
        self.trigger_callback = trigger_callback
        self.thread = None
        self.stop_event = threading.Event()
        self.running = False

    def start(self) -> None:
        if self.config.controller_backend != "pygame":
            logger.info("Controller monitoring disabled because backend=%s", self.config.controller_backend)
            return

        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run, name="controller-monitor", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread is not None and self.thread.is_alive():
            self.thread.join(timeout=2.0)

    def _run(self) -> None:
        pygame = None
        try:
            import pygame

            pygame.init()
            pygame.joystick.init()
            self.running = True
            hold_state: Dict[int, Dict] = {}

            while not self.stop_event.is_set():
                try:
                    pygame.event.pump()
                    events = pygame.event.get()
                except (KeyError, SystemError):
                    logger.exception("Controller event queue read failed; continuing monitor loop")
                    try:
                        pygame.joystick.quit()
                        pygame.joystick.init()
                    except Exception:
                        logger.debug("Failed to reinitialize joystick subsystem", exc_info=True)
                    time.sleep(self.config.controller_poll_interval_seconds)
                    continue

                for event in events:
                    joy = getattr(event, "instance_id", getattr(event, "joy", None))
                    if event.type == pygame.JOYDEVICEADDED:
                        joystick = pygame.joystick.Joystick(event.device_index)
                        joystick.init()
                        logger.info("Controller connected: %s", joystick.get_name())
                        continue

                    if joy is None:
                        continue

                    joystick = self._get_joystick(pygame, joy)
                    if joystick is None:
                        continue

                    profile = self._match_profile(joystick.get_name())
                    if profile is None:
                        continue

                    current = hold_state.setdefault(
                        joy,
                        {
                            "started_at": None,
                            "cancelled": False,
                            "home_button": None,
                            "joystick_name": joystick.get_name(),
                        },
                    )
                    current["joystick_name"] = joystick.get_name()
                    home_buttons = set(profile.home_button_indices)

                    if event.type == pygame.JOYBUTTONDOWN:
                        if event.button in home_buttons:
                            current["started_at"] = time.monotonic()
                            current["cancelled"] = False
                            current["home_button"] = event.button
                        elif current.get("started_at") is not None and self.config.require_quiet_controller_hold:
                            self._cancel_hold(current)
                    elif event.type == pygame.JOYBUTTONUP and event.button in home_buttons:
                        current["started_at"] = None
                        current["cancelled"] = False
                        current["home_button"] = None
                    elif (
                        event.type == pygame.JOYAXISMOTION
                        and current.get("started_at") is not None
                        and abs(event.value) >= self.config.analog_deadzone
                        and self.config.require_quiet_controller_hold
                    ):
                        self._cancel_hold(current)
                    elif (
                        event.type == pygame.JOYHATMOTION
                        and current.get("started_at") is not None
                        and event.value != (0, 0)
                        and self.config.require_quiet_controller_hold
                    ):
                        self._cancel_hold(current)

                self._flush_holds(hold_state)
                time.sleep(self.config.controller_poll_interval_seconds)
        except Exception:
            logger.exception("Controller monitor crashed")
        finally:
            self.running = False
            try:
                pygame.joystick.quit()
                pygame.quit()
            except Exception:
                logger.debug("Failed to shut down pygame cleanly", exc_info=True)

    def _flush_holds(self, hold_state: Dict[int, Dict]) -> None:
        for joy, state in hold_state.items():
            started_at = state.get("started_at")
            if started_at is None or state.get("cancelled"):
                continue
            if time.monotonic() - started_at < self.config.home_button_hold_seconds:
                continue

            logger.info(
                "Controller shortcut detected on joystick %s (%s) with button %s",
                joy,
                state.get("joystick_name", "<unknown>"),
                state.get("home_button"),
            )
            state["started_at"] = None
            state["cancelled"] = False
            state["home_button"] = None
            try:
                self.trigger_callback("controller_hold")
            except Exception:
                logger.exception("Controller callback failed")

    def _cancel_hold(self, state: Dict) -> None:
        if state.get("cancelled"):
            return
        state["cancelled"] = True

    def _match_profile(self, joystick_name: str) -> Optional[ControllerProfile]:
        name = joystick_name.lower()
        for profile in self.config.controller_profiles:
            if profile.name_contains.lower() in name:
                return profile
        return None

    def _get_joystick(self, pygame_module, instance_id: int):
        count = pygame_module.joystick.get_count()
        for index in range(count):
            joystick = pygame_module.joystick.Joystick(index)
            if joystick.get_instance_id() == instance_id:
                return joystick
        return None
