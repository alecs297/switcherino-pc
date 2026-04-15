import logging
from typing import Dict

from .commands import run_process
from .config import APP_DIR, AudioSettings, DisplaySettings, ModeProfile


logger = logging.getLogger(__name__)

DISPLAY_SWITCH_MAP = {
    "internal_only": [r"C:\Windows\System32\DisplaySwitch.exe", "/internal"],
    "external_only": [r"C:\Windows\System32\DisplaySwitch.exe", "/external"],
    "clone": [r"C:\Windows\System32\DisplaySwitch.exe", "/clone"],
    "extend": [r"C:\Windows\System32\DisplaySwitch.exe", "/extend"],
}

AUDIO_HELPER_PATH = APP_DIR / "scripts" / "audio-helper.ps1"


async def apply_display_settings(settings: DisplaySettings, label: str) -> Dict:
    topology = str(settings.topology or "").strip()
    if not topology:
        logger.info("Skipping %s because no display topology is configured", label)
        return {"step": label, "skipped": True, "reason": "display_not_configured"}

    command = DISPLAY_SWITCH_MAP.get(topology)
    if command is None:
        logger.warning("Profile %s requested unsupported display topology: %s", label, topology)
        return {
            "step": label,
            "skipped": False,
            "returncode": 1,
            "stdout": "",
            "stderr": f"Unsupported display topology: {topology}",
        }

    logger.info("Applying display topology for %s: %s", label, topology)
    return await run_process(command, label)

async def apply_audio_settings(settings: AudioSettings, label: str) -> Dict:
    if not settings.enabled:
        logger.info("Skipping %s because audio switching is disabled", label)
        return {"step": label, "skipped": True, "reason": "audio_disabled"}

    endpoint_id = str(settings.endpoint_id or "").strip()
    if not endpoint_id:
        logger.warning("Audio switching is enabled for %s but no endpoint is configured", label)
        return {"step": label, "skipped": True, "reason": "audio_not_configured"}

    if not AUDIO_HELPER_PATH.exists():
        logger.error("Audio helper script is missing: %s", AUDIO_HELPER_PATH)
        return {
            "step": label,
            "skipped": False,
            "returncode": 1,
            "stdout": "",
            "stderr": f"Audio helper script is missing: {AUDIO_HELPER_PATH}",
        }
    command = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(AUDIO_HELPER_PATH),
        "-Action",
        "apply",
        "-EndpointId",
        endpoint_id,
    ]
    if settings.volume_scalar is not None:
        command.extend(["-VolumeScalar", str(settings.volume_scalar)])

    logger.info(
        "Applying audio endpoint for %s: %s (%s)",
        label,
        settings.endpoint_name or "unnamed endpoint",
        endpoint_id,
    )
    return await run_process(command, label)


def profile_is_configured(profile: ModeProfile) -> bool:
    return bool(str(profile.display.topology or "").strip())
