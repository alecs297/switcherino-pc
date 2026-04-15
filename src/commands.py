import asyncio
import logging
import subprocess
from typing import Dict, Optional, Sequence, Union


logger = logging.getLogger(__name__)


async def run_process(
    command: Union[str, Sequence[str]],
    label: str,
    *,
    shell: bool = False,
    cwd: Optional[str] = None,
) -> Dict:
    logger.info("Running process for %s: %s", label, command)
    completed = await asyncio.to_thread(
        subprocess.run,
        command,
        shell=shell,
        cwd=cwd,
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


async def run_configured_command(command: str, label: str) -> Dict:
    text = str(command or "").strip()
    if not text:
        logger.info("Skipping %s because no command is configured", label)
        return {"step": label, "skipped": True}

    logger.info("Running command for %s: %s", label, text)
    return await run_process(text, label, shell=True)
