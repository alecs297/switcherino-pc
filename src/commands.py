import asyncio
import logging
import os
import re
import shlex
import subprocess
from os import PathLike
from typing import Dict, Optional, Sequence, Union


logger = logging.getLogger(__name__)
URI_PATTERN = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://")


async def run_process(
    command: Union[str, Sequence[str]],
    label: str,
    *,
    cwd: Optional[str] = None,
    env: Optional[Dict[str, Union[str, PathLike[str]]]] = None,
) -> Dict:
    logger.info("Running process for %s: %s", label, command)
    completed = await asyncio.to_thread(
        subprocess.run,
        command,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    result = {
        "step": label,
        "skipped": False,
        "returncode": completed.returncode,
        "stdout": (completed.stdout or "").strip()[:500],
        "stderr": (completed.stderr or "").strip()[:500],
    }
    if completed.returncode != 0:
        logger.warning("Process %s failed with code %s", label, completed.returncode)
    return result


def _parse_command_text(command: str) -> Sequence[str]:
    return shlex.split(command, posix=False)


def _open_with_shell(target: str) -> None:
    os.startfile(target)


def _extract_uri_target(command: str) -> Optional[str]:
    text = str(command or "").strip()
    if URI_PATTERN.match(text):
        return text

    parts = _parse_command_text(text)
    if len(parts) >= 4 and parts[0].lower() == "cmd" and parts[1].lower() == "/c" and parts[2].lower() == "start":
        for part in reversed(parts[3:]):
            candidate = str(part or "").strip().strip('"')
            if URI_PATTERN.match(candidate):
                return candidate
    return None


async def run_configured_command(command: str, label: str) -> Dict:
    text = str(command or "").strip()
    if not text:
        logger.info("Skipping %s because no command is configured", label)
        return {"step": label, "skipped": True}

    logger.info("Running command for %s: %s", label, text)
    uri_target = _extract_uri_target(text)
    if uri_target is not None:
        await asyncio.to_thread(_open_with_shell, uri_target)
        return {"step": label, "skipped": False, "returncode": 0, "stdout": "", "stderr": ""}

    return await run_process(_parse_command_text(text), label)
