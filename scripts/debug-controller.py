import argparse
import os
import time
from typing import Dict, List, Set, Tuple


DEFAULT_DEADZONE = 0.35
DEFAULT_HOLD_SECONDS = 3.0
AXIS_MOTION_EPSILON = 0.05
CONTROLLER_AXIS_SCALE = 32768.0
CONTROLLER_BUTTON_NAMES = (
    ("a", "CONTROLLER_BUTTON_A"),
    ("b", "CONTROLLER_BUTTON_B"),
    ("x", "CONTROLLER_BUTTON_X"),
    ("y", "CONTROLLER_BUTTON_Y"),
    ("back", "CONTROLLER_BUTTON_BACK"),
    ("guide", "CONTROLLER_BUTTON_GUIDE"),
    ("start", "CONTROLLER_BUTTON_START"),
    ("leftstick", "CONTROLLER_BUTTON_LEFTSTICK"),
    ("rightstick", "CONTROLLER_BUTTON_RIGHTSTICK"),
    ("leftshoulder", "CONTROLLER_BUTTON_LEFTSHOULDER"),
    ("rightshoulder", "CONTROLLER_BUTTON_RIGHTSHOULDER"),
    ("dpad_up", "CONTROLLER_BUTTON_DPAD_UP"),
    ("dpad_down", "CONTROLLER_BUTTON_DPAD_DOWN"),
    ("dpad_left", "CONTROLLER_BUTTON_DPAD_LEFT"),
    ("dpad_right", "CONTROLLER_BUTTON_DPAD_RIGHT"),
)
CONTROLLER_AXIS_NAMES = (
    ("leftx", "CONTROLLER_AXIS_LEFTX"),
    ("lefty", "CONTROLLER_AXIS_LEFTY"),
    ("rightx", "CONTROLLER_AXIS_RIGHTX"),
    ("righty", "CONTROLLER_AXIS_RIGHTY"),
    ("triggerleft", "CONTROLLER_AXIS_TRIGGERLEFT"),
    ("triggerright", "CONTROLLER_AXIS_TRIGGERRIGHT"),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inspect pygame controller events and help identify the PS/Xbox home button."
    )
    parser.add_argument(
        "--deadzone",
        type=float,
        default=DEFAULT_DEADZONE,
        help=f"Minimum absolute axis value to log (default: {DEFAULT_DEADZONE}).",
    )
    parser.add_argument(
        "--hold-seconds",
        type=float,
        default=DEFAULT_HOLD_SECONDS,
        help=f"Duration used to report a home-button long press (default: {DEFAULT_HOLD_SECONDS}).",
    )
    parser.add_argument(
        "--poll-sleep",
        type=float,
        default=0.02,
        help="Sleep between event polls in seconds (default: 0.02).",
    )
    return parser.parse_args()


def describe_joysticks(pygame_module, controller_module, button_labels: Dict[int, str]) -> None:
    count = pygame_module.joystick.get_count()
    if count == 0:
        print("No controller detected. Connect one, then rerun the script.")
        return

    print(f"Detected {count} controller(s):")
    for index in range(count):
        joystick = pygame_module.joystick.Joystick(index)
        joystick.init()
        print(
            f"  [{index}] name={joystick.get_name()!r} "
            f"instance_id={joystick.get_instance_id()} "
            f"guid={joystick.get_guid()} "
            f"buttons={joystick.get_numbuttons()} "
            f"axes={joystick.get_numaxes()} "
            f"hats={joystick.get_numhats()}"
        )
        if controller_module is not None and controller_module.is_controller(index):
            controller = controller_module.Controller.from_joystick(joystick)
            if not controller.get_init():
                controller.init()
            mapping = controller.get_mapping()
            shortcut_names = ", ".join(
                f"{name}={mapping.get(name)}"
                for name in ("guide", "leftshoulder", "rightshoulder", "back", "start")
                if mapping.get(name)
            )
            print(f"      mode='controller' mapping: {shortcut_names}")
            print(f"      detectable controller buttons: {', '.join(button_labels.values())}")
    print()


def read_pressed_buttons(joystick) -> Set[int]:
    return {
        button_index
        for button_index in range(joystick.get_numbuttons())
        if joystick.get_button(button_index)
    }


def read_axes(joystick) -> Tuple[float, ...]:
    return tuple(float(joystick.get_axis(axis_index)) for axis_index in range(joystick.get_numaxes()))


def read_hats(joystick) -> Tuple[Tuple[int, int], ...]:
    return tuple(tuple(joystick.get_hat(hat_index)) for hat_index in range(joystick.get_numhats()))


def init_controller_module():
    try:
        import pygame._sdl2.controller as controller_module

        controller_module.init()
        controller_module.set_eventstate(False)
        return controller_module
    except Exception as exc:
        print(f"[info] SDL controller API unavailable, falling back to joystick polling: {exc}")
        return None


def controller_button_labels(pygame_module) -> Dict[int, str]:
    labels: Dict[int, str] = {}
    for label, constant_name in CONTROLLER_BUTTON_NAMES:
        button_id = getattr(pygame_module, constant_name, None)
        if button_id is None:
            continue
        labels[int(button_id)] = label
    return labels


def controller_axis_specs(pygame_module) -> List[Tuple[int, str]]:
    specs: List[Tuple[int, str]] = []
    for label, constant_name in CONTROLLER_AXIS_NAMES:
        axis_id = getattr(pygame_module, constant_name, None)
        if axis_id is None:
            continue
        specs.append((int(axis_id), label))
    return specs


def read_controller_buttons(controller, button_labels: Dict[int, str]) -> Set[int]:
    return {
        button_id
        for button_id in button_labels
        if controller.get_button(button_id)
    }


def read_controller_axes(controller, axis_specs: List[Tuple[int, str]]) -> Tuple[float, ...]:
    return tuple(float(controller.get_axis(axis_id)) / CONTROLLER_AXIS_SCALE for axis_id, _ in axis_specs)


def poll_joysticks(
    pygame_module,
    controller_module,
    button_labels: Dict[int, str],
    axis_specs: List[Tuple[int, str]],
) -> List[Dict[str, object]]:
    snapshots: List[Dict[str, object]] = []
    for index in range(pygame_module.joystick.get_count()):
        try:
            joystick = pygame_module.joystick.Joystick(index)
            if not joystick.get_init():
                joystick.init()
            if controller_module is not None and controller_module.is_controller(index):
                controller = controller_module.Controller.from_joystick(joystick)
                if not controller.get_init():
                    controller.init()
                snapshots.append(
                    {
                        "index": index,
                        "instance_id": joystick.get_instance_id(),
                        "name": str(getattr(controller, "name", joystick.get_name()) or joystick.get_name()),
                        "mode": "controller",
                        "pressed_buttons": read_controller_buttons(controller, button_labels),
                        "axes": read_controller_axes(controller, axis_specs),
                        "hats": tuple(),
                    }
                )
                continue

            snapshots.append(
                {
                    "index": index,
                    "instance_id": joystick.get_instance_id(),
                    "name": joystick.get_name(),
                    "mode": "joystick",
                    "pressed_buttons": read_pressed_buttons(joystick),
                    "axes": read_axes(joystick),
                    "hats": read_hats(joystick),
                }
            )
        except Exception as exc:
            print(f"[warn] failed to read controller index={index}: {exc}")
    return snapshots


def iter_axis_changes(
    previous_axes: Tuple[float, ...],
    current_axes: Tuple[float, ...],
    deadzone: float,
) -> List[Tuple[int, float]]:
    changes = []
    for axis_index, current_value in enumerate(current_axes):
        previous_value = previous_axes[axis_index] if axis_index < len(previous_axes) else 0.0
        if abs(current_value) < deadzone:
            continue
        if abs(current_value - previous_value) < AXIS_MOTION_EPSILON:
            continue
        changes.append((axis_index, current_value))
    return changes


def iter_hat_changes(
    previous_hats: Tuple[Tuple[int, int], ...],
    current_hats: Tuple[Tuple[int, int], ...],
) -> List[Tuple[int, Tuple[int, int]]]:
    changes = []
    for hat_index, current_value in enumerate(current_hats):
        previous_value = previous_hats[hat_index] if hat_index < len(previous_hats) else (0, 0)
        if current_value == previous_value or current_value == (0, 0):
            continue
        changes.append((hat_index, current_value))
    return changes


def main() -> int:
    args = parse_args()

    try:
        os.environ.setdefault("SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS", "1")
        import pygame
    except Exception as exc:
        print(f"Unable to import pygame: {exc}")
        return 1

    pygame.init()
    pygame.joystick.init()
    pygame.event.set_blocked(None)
    controller_module = init_controller_module()
    button_labels = controller_button_labels(pygame)
    axis_specs = controller_axis_specs(pygame)

    print("Controller debug started. Press Ctrl+C to stop.\n")
    print("Tip: press the PS/Xbox button once to find its button index or SDL controller name,")
    print(f"then hold it for {args.hold_seconds:.1f}s to validate long-press detection.\n")

    describe_joysticks(pygame, controller_module, button_labels)

    hold_state: Dict[int, Dict[str, object]] = {}
    connected_joysticks: Dict[int, str] = {}

    try:
        while True:
            pygame.event.pump()
            if controller_module is not None:
                controller_module.update()
            snapshots = poll_joysticks(pygame, controller_module, button_labels, axis_specs)
            current_joysticks = {snapshot["instance_id"]: snapshot["name"] for snapshot in snapshots}

            for snapshot in snapshots:
                joy = int(snapshot["instance_id"])
                if joy in connected_joysticks:
                    continue
                print(
                    f"[device-added] index={snapshot['index']} "
                    f"instance_id={joy} name={snapshot['name']!r} mode={snapshot['mode']}"
                )

            for joy, name in connected_joysticks.items():
                if joy in current_joysticks:
                    continue
                print(f"[device-removed] instance_id={joy} name={name!r}")
                hold_state.pop(joy, None)

            for snapshot in snapshots:
                joy = int(snapshot["instance_id"])
                joystick_name = str(snapshot["name"])
                state = hold_state.setdefault(
                    joy,
                    {
                        "candidate_button": None,
                        "started_at": None,
                        "long_press_reported": False,
                        "cancelled": False,
                        "pressed_buttons": set(snapshot["pressed_buttons"]),
                        "last_axes": snapshot["axes"],
                        "last_hats": snapshot["hats"],
                    },
                )

                previous_buttons = set(state.get("pressed_buttons", set()))
                pressed_buttons = set(snapshot["pressed_buttons"])
                pressed_now = sorted(pressed_buttons - previous_buttons)
                released_now = sorted(previous_buttons - pressed_buttons)

                for button in pressed_now:
                    state["candidate_button"] = button
                    state["started_at"] = time.monotonic()
                    state["long_press_reported"] = False
                    state["cancelled"] = False
                    label = button_labels.get(button, str(button))
                    print(f"[button-down] joy={joy} name={joystick_name!r} button={button} label={label}")

                for button in released_now:
                    started_at = state.get("started_at")
                    held_for = 0.0 if started_at is None else time.monotonic() - float(started_at)
                    label = button_labels.get(button, str(button))
                    print(
                        f"[button-up] joy={joy} name={joystick_name!r} "
                        f"button={button} label={label} held_for={held_for:.2f}s"
                    )
                    if state.get("candidate_button") == button:
                        state["started_at"] = None
                        state["long_press_reported"] = False
                        state["cancelled"] = False

                for axis_index, value in iter_axis_changes(
                    tuple(state.get("last_axes", ())),
                    tuple(snapshot["axes"]),
                    args.deadzone,
                ):
                    state["cancelled"] = True
                    print(
                        f"[axis] joy={joy} name={joystick_name!r} axis={axis_index} "
                        f"value={value:+.3f}"
                    )

                for hat_index, value in iter_hat_changes(
                    tuple(state.get("last_hats", ())),
                    tuple(snapshot["hats"]),
                ):
                    state["cancelled"] = True
                    print(f"[hat] joy={joy} name={joystick_name!r} hat={hat_index} value={value}")

                state["pressed_buttons"] = pressed_buttons
                state["last_axes"] = snapshot["axes"]
                state["last_hats"] = snapshot["hats"]

            now = time.monotonic()
            for joy, state in hold_state.items():
                started_at = state.get("started_at")
                if started_at is None or state.get("long_press_reported"):
                    continue
                if state.get("cancelled"):
                    continue
                held_for = now - float(started_at)
                if held_for < args.hold_seconds:
                    continue

                print(
                    f"[long-press] joy={joy} button={state.get('candidate_button')} "
                    f"held_for={held_for:.2f}s"
                )
                state["long_press_reported"] = True

            connected_joysticks = current_joysticks
            time.sleep(args.poll_sleep)
    except KeyboardInterrupt:
        print("\nStopped controller debug.")
        return 0
    finally:
        if controller_module is not None:
            controller_module.quit()
        pygame.quit()


if __name__ == "__main__":
    raise SystemExit(main())
