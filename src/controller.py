import asyncio
import logging
import os
import threading
import time
from typing import Callable, Dict, List, Optional, Set, Tuple

from .config import AppConfig, ControllerProfile


logger = logging.getLogger(__name__)


class ControllerMonitor:
    _AXIS_MOTION_EPSILON = 0.05
    _CONTROLLER_BUTTON_NAMES = (
        "CONTROLLER_BUTTON_A",
        "CONTROLLER_BUTTON_B",
        "CONTROLLER_BUTTON_X",
        "CONTROLLER_BUTTON_Y",
        "CONTROLLER_BUTTON_BACK",
        "CONTROLLER_BUTTON_GUIDE",
        "CONTROLLER_BUTTON_START",
        "CONTROLLER_BUTTON_LEFTSTICK",
        "CONTROLLER_BUTTON_RIGHTSTICK",
        "CONTROLLER_BUTTON_LEFTSHOULDER",
        "CONTROLLER_BUTTON_RIGHTSHOULDER",
        "CONTROLLER_BUTTON_DPAD_UP",
        "CONTROLLER_BUTTON_DPAD_DOWN",
        "CONTROLLER_BUTTON_DPAD_LEFT",
        "CONTROLLER_BUTTON_DPAD_RIGHT",
    )
    _CONTROLLER_AXIS_NAMES = (
        "CONTROLLER_AXIS_LEFTX",
        "CONTROLLER_AXIS_LEFTY",
        "CONTROLLER_AXIS_RIGHTX",
        "CONTROLLER_AXIS_RIGHTY",
        "CONTROLLER_AXIS_TRIGGERLEFT",
        "CONTROLLER_AXIS_TRIGGERRIGHT",
    )
    _CONTROLLER_AXIS_SCALE = 32768.0

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
        controller_module = None
        try:
            os.environ["SDL_VIDEO_ALLOW_SCREENSAVER"] = "1"
            os.environ.setdefault("SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS", "1")
            import pygame

            pygame.init()
            pygame.joystick.init()
            controller_module = self._init_controller_module()
            self._discard_all_events(pygame)
            self.running = True
            hold_state: Dict[int, Dict] = {}
            connected_joysticks: Dict[int, str] = {}

            while not self.stop_event.is_set():
                try:
                    pygame.event.pump()
                    if controller_module is not None:
                        controller_module.update()
                    snapshots = self._poll_devices(pygame, controller_module)
                except Exception:
                    logger.exception("Controller state poll failed; continuing monitor loop")
                    try:
                        if controller_module is not None:
                            controller_module.quit()
                        pygame.joystick.quit()
                        pygame.joystick.init()
                        controller_module = self._init_controller_module()
                        self._discard_all_events(pygame)
                    except Exception:
                        logger.debug("Failed to reinitialize joystick subsystem", exc_info=True)
                    time.sleep(self.config.controller_poll_interval_seconds)
                    continue

                current_joysticks = {snapshot["instance_id"]: snapshot["name"] for snapshot in snapshots}
                for joy, name in current_joysticks.items():
                    if joy not in connected_joysticks:
                        logger.info("Controller connected: %s", name)

                for joy, name in connected_joysticks.items():
                    if joy in current_joysticks:
                        continue

                    hold_state.pop(joy, None)
                    logger.info("Controller disconnected: %s", name)

                for snapshot in snapshots:
                    joy = snapshot["instance_id"]
                    profile = self._match_profile(snapshot["name"])
                    if profile is None:
                        continue

                    current = hold_state.setdefault(
                        joy,
                        {
                            "started_at": None,
                            "cancelled": False,
                            "pressed_buttons": set(snapshot["pressed_buttons"]),
                            "trigger_buttons": set(),
                            "joystick_name": snapshot["name"],
                            "last_axes": snapshot["axes"],
                            "last_hats": snapshot["hats"],
                        },
                    )
                    current["joystick_name"] = snapshot["name"]
                    shortcut_buttons = set(profile.shortcut_button_indices)

                    pressed_buttons = set(snapshot["pressed_buttons"])
                    if pressed_buttons != current.get("pressed_buttons", set()):
                        current["pressed_buttons"] = pressed_buttons
                        self._refresh_shortcut_state(current, shortcut_buttons)

                    if (
                        current.get("started_at") is not None
                        and self.config.require_quiet_controller_hold
                        and (
                            self._has_meaningful_axis_motion(current.get("last_axes", ()), snapshot["axes"])
                            or self._has_meaningful_hat_motion(current.get("last_hats", ()), snapshot["hats"])
                        )
                    ):
                        self._cancel_hold(current)

                    current["last_axes"] = snapshot["axes"]
                    current["last_hats"] = snapshot["hats"]

                connected_joysticks = current_joysticks
                self._flush_holds(hold_state)
                time.sleep(self.config.controller_poll_interval_seconds)
        except Exception:
            logger.exception("Controller monitor crashed")
        finally:
            self.running = False
            try:
                if pygame is not None:
                    if controller_module is not None:
                        controller_module.quit()
                    pygame.joystick.quit()
                    pygame.quit()
            except Exception:
                logger.debug("Failed to shut down pygame cleanly", exc_info=True)

    def _flush_holds(self, hold_state: Dict[int, Dict]) -> None:
        for joy, state in hold_state.items():
            started_at = state.get("started_at")
            if started_at is None or state.get("cancelled"):
                continue
            if time.monotonic() - started_at < self.config.controller_shortcut_hold_seconds:
                continue

            logger.info(
                "Controller shortcut detected on joystick %s (%s) with buttons %s",
                joy,
                state.get("joystick_name", "<unknown>"),
                sorted(state.get("trigger_buttons", set())),
            )
            state["started_at"] = None
            state["cancelled"] = False
            state["trigger_buttons"] = set()
            try:
                self.trigger_callback("controller_hold")
            except Exception:
                logger.exception("Controller callback failed")

    def _cancel_hold(self, state: Dict) -> None:
        if state.get("cancelled"):
            return
        state["cancelled"] = True

    def _refresh_shortcut_state(self, state: Dict, shortcut_buttons: Set[int]) -> None:
        pressed_buttons = state.get("pressed_buttons", set())
        if pressed_buttons == shortcut_buttons:
            if state.get("started_at") is None or state.get("cancelled"):
                state["started_at"] = time.monotonic()
                state["cancelled"] = False
                state["trigger_buttons"] = set(shortcut_buttons)
            return

        state["started_at"] = None
        state["trigger_buttons"] = set()
        if pressed_buttons.intersection(shortcut_buttons):
            state["cancelled"] = True
        else:
            state["cancelled"] = False

    def _match_profile(self, joystick_name: str) -> Optional[ControllerProfile]:
        name = joystick_name.lower()
        for profile in self.config.controller_profiles:
            if profile.name_contains.lower() in name:
                return profile
        return None

    def _discard_all_events(self, pygame_module) -> None:
        pygame_module.event.set_blocked(None)

    def _init_controller_module(self):
        try:
            import pygame._sdl2.controller as controller_module

            controller_module.init()
            controller_module.set_eventstate(False)
            logger.debug("Using SDL controller API for recognized gamepads")
            return controller_module
        except Exception:
            logger.debug("SDL controller API unavailable; using joystick polling", exc_info=True)
            return None

    def _poll_devices(self, pygame_module, controller_module) -> List[Dict]:
        snapshots = []
        count = pygame_module.joystick.get_count()
        for index in range(count):
            try:
                joystick = pygame_module.joystick.Joystick(index)
                if not joystick.get_init():
                    joystick.init()

                snapshot = self._poll_controller_snapshot(pygame_module, controller_module, index, joystick)
                if snapshot is None:
                    snapshot = self._poll_joystick_snapshot(joystick)
                snapshots.append(snapshot)
            except Exception:
                logger.debug("Failed to read controller at index %s", index, exc_info=True)
        return snapshots

    def _poll_controller_snapshot(self, pygame_module, controller_module, index: int, joystick) -> Optional[Dict]:
        if controller_module is None or not controller_module.is_controller(index):
            return None

        try:
            controller = controller_module.Controller.from_joystick(joystick)
            if not controller.get_init():
                controller.init()
            return {
                "instance_id": joystick.get_instance_id(),
                "name": str(getattr(controller, "name", joystick.get_name()) or joystick.get_name()),
                "pressed_buttons": self._read_controller_buttons(pygame_module, controller),
                "axes": self._read_controller_axes(pygame_module, controller),
                "hats": tuple(),
            }
        except Exception:
            logger.debug("Failed to read SDL controller state at index %s; falling back to joystick", index, exc_info=True)
            return None

    def _poll_joystick_snapshot(self, joystick) -> Dict:
        return {
            "instance_id": joystick.get_instance_id(),
            "name": joystick.get_name(),
            "pressed_buttons": self._read_pressed_buttons(joystick),
            "axes": self._read_axes(joystick),
            "hats": self._read_hats(joystick),
        }

    def _read_pressed_buttons(self, joystick) -> Set[int]:
        return {
            button_index
            for button_index in range(joystick.get_numbuttons())
            if joystick.get_button(button_index)
        }

    def _read_controller_buttons(self, pygame_module, controller) -> Set[int]:
        pressed_buttons = set()
        for constant_name in self._CONTROLLER_BUTTON_NAMES:
            button_id = getattr(pygame_module, constant_name, None)
            if button_id is None:
                continue
            if controller.get_button(button_id):
                pressed_buttons.add(int(button_id))
        return pressed_buttons

    def _read_controller_axes(self, pygame_module, controller) -> Tuple[float, ...]:
        axis_values = []
        for constant_name in self._CONTROLLER_AXIS_NAMES:
            axis_id = getattr(pygame_module, constant_name, None)
            if axis_id is None:
                continue
            axis_values.append(float(controller.get_axis(axis_id)) / self._CONTROLLER_AXIS_SCALE)
        return tuple(axis_values)

    def _read_axes(self, joystick) -> Tuple[float, ...]:
        return tuple(float(joystick.get_axis(axis_index)) for axis_index in range(joystick.get_numaxes()))

    def _read_hats(self, joystick) -> Tuple[Tuple[int, int], ...]:
        return tuple(tuple(joystick.get_hat(hat_index)) for hat_index in range(joystick.get_numhats()))

    def _has_meaningful_axis_motion(
        self,
        previous_axes: Tuple[float, ...],
        current_axes: Tuple[float, ...],
    ) -> bool:
        for axis_index, current_value in enumerate(current_axes):
            previous_value = previous_axes[axis_index] if axis_index < len(previous_axes) else 0.0
            if abs(current_value) < self.config.analog_deadzone:
                continue
            if abs(current_value - previous_value) >= self._AXIS_MOTION_EPSILON:
                return True
        return False

    def _has_meaningful_hat_motion(
        self,
        previous_hats: Tuple[Tuple[int, int], ...],
        current_hats: Tuple[Tuple[int, int], ...],
    ) -> bool:
        for hat_index, current_value in enumerate(current_hats):
            previous_value = previous_hats[hat_index] if hat_index < len(previous_hats) else (0, 0)
            if current_value != previous_value and current_value != (0, 0):
                return True
        return False
