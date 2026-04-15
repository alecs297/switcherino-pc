import argparse
import time
from typing import Dict, Tuple


DEFAULT_DEADZONE = 0.35
DEFAULT_HOLD_SECONDS = 3.0


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


def describe_joysticks(pygame_module) -> None:
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
    print()


def get_joystick(pygame_module, instance_id: int):
    for index in range(pygame_module.joystick.get_count()):
        joystick = pygame_module.joystick.Joystick(index)
        if joystick.get_instance_id() == instance_id:
            return joystick
    return None


def main() -> int:
    args = parse_args()

    try:
        import pygame
    except Exception as exc:
        print(f"Unable to import pygame: {exc}")
        return 1

    pygame.init()
    pygame.joystick.init()

    print("Controller debug started. Press Ctrl+C to stop.\n")
    print("Tip: press the PS/Xbox button once to find its button index,")
    print(f"then hold it for {args.hold_seconds:.1f}s to validate long-press detection.\n")

    describe_joysticks(pygame)

    hold_state: Dict[int, Dict[str, object]] = {}
    last_axis_values: Dict[Tuple[int, int], float] = {}

    try:
        while True:
            pygame.event.pump()
            for event in pygame.event.get():
                joy = getattr(event, "instance_id", getattr(event, "joy", None))

                if event.type == pygame.JOYDEVICEADDED:
                    joystick = pygame.joystick.Joystick(event.device_index)
                    joystick.init()
                    print(
                        f"[device-added] index={event.device_index} "
                        f"instance_id={joystick.get_instance_id()} name={joystick.get_name()!r}"
                    )
                    continue

                if event.type == pygame.JOYDEVICEREMOVED:
                    print(f"[device-removed] instance_id={joy}")
                    hold_state.pop(joy, None)
                    continue

                if joy is None:
                    continue

                joystick = get_joystick(pygame, joy)
                joystick_name = joystick.get_name() if joystick is not None else "<unknown>"
                state = hold_state.setdefault(
                    joy,
                    {
                        "candidate_button": None,
                        "started_at": None,
                        "long_press_reported": False,
                        "cancelled": False,
                    },
                )

                if event.type == pygame.JOYBUTTONDOWN:
                    state["candidate_button"] = event.button
                    state["started_at"] = time.monotonic()
                    state["long_press_reported"] = False
                    state["cancelled"] = False
                    print(f"[button-down] joy={joy} name={joystick_name!r} button={event.button}")
                elif event.type == pygame.JOYBUTTONUP:
                    started_at = state.get("started_at")
                    held_for = 0.0 if started_at is None else time.monotonic() - float(started_at)
                    print(
                        f"[button-up] joy={joy} name={joystick_name!r} "
                        f"button={event.button} held_for={held_for:.2f}s"
                    )
                    if state.get("candidate_button") == event.button:
                        state["started_at"] = None
                        state["long_press_reported"] = False
                        state["cancelled"] = False
                elif event.type == pygame.JOYAXISMOTION:
                    value = float(event.value)
                    if abs(value) < args.deadzone:
                        continue
                    key = (joy, event.axis)
                    previous_value = last_axis_values.get(key)
                    if previous_value is None or abs(previous_value - value) >= 0.05:
                        last_axis_values[key] = value
                        state["cancelled"] = True
                        print(
                            f"[axis] joy={joy} name={joystick_name!r} axis={event.axis} "
                            f"value={value:+.3f}"
                        )
                elif event.type == pygame.JOYHATMOTION:
                    if event.value != (0, 0):
                        state["cancelled"] = True
                        print(f"[hat] joy={joy} name={joystick_name!r} hat={event.hat} value={event.value}")

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

            time.sleep(args.poll_sleep)
    except KeyboardInterrupt:
        print("\nStopped controller debug.")
        return 0
    finally:
        pygame.quit()


if __name__ == "__main__":
    raise SystemExit(main())
