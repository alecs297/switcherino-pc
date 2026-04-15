import ctypes
import ctypes.wintypes
import json
import logging
import subprocess
from typing import List, Optional


logger = logging.getLogger(__name__)


def _normalize_window_text(value: str) -> str:
    return " ".join(str(value or "").split()).lower()


def is_process_running(process_name: str) -> bool:
    completed = subprocess.run(
        ["tasklist", "/FI", f"IMAGENAME eq {process_name}"],
        capture_output=True,
        text=True,
        check=False,
    )
    return process_name.lower() in (completed.stdout or "").lower()


def get_process_rows() -> List[dict]:
    completed = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-Command",
            "Get-CimInstance Win32_Process | Select-Object ProcessId,Name,CommandLine | ConvertTo-Json -Depth 3",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    text = (completed.stdout or "").strip()
    if not text:
        return []

    data = json.loads(text)
    if isinstance(data, dict):
        data = [data]

    rows = []
    for item in data:
        rows.append(
            {
                "pid": int(item.get("ProcessId", 0) or 0),
                "name": str(item.get("Name", "") or ""),
                "command_line": str(item.get("CommandLine", "") or ""),
            }
        )
    return rows


def is_pid_running(pid: int) -> bool:
    if pid <= 0:
        return False
    completed = subprocess.run(
        ["tasklist", "/FI", f"PID eq {pid}"],
        capture_output=True,
        text=True,
        check=False,
    )
    output = (completed.stdout or "").lower()
    return f" {pid} " in output or output.strip().endswith(str(pid))


def get_visible_windows() -> List[dict]:
    user32 = ctypes.windll.user32
    windows = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
    def enum_windows_proc(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, len(buffer))
        title = buffer.value.strip()
        if title:
            pid = ctypes.wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            windows.append({"hwnd": int(hwnd), "pid": int(pid.value), "title": title})
        return True

    user32.EnumWindows(enum_windows_proc, 0)
    return windows


def get_visible_window_titles() -> List[str]:
    return [window["title"] for window in get_visible_windows()]


def find_windows_by_title(title_contains: str) -> List[dict]:
    fragment = _normalize_window_text(title_contains)
    if not fragment:
        return []
    return [window for window in get_visible_windows() if fragment in _normalize_window_text(window["title"])]


def debug_visible_windows_for_title(title_contains: str) -> dict:
    fragment = _normalize_window_text(title_contains)
    windows = get_visible_windows()
    matches = [window for window in windows if fragment and fragment in _normalize_window_text(window["title"])]
    return {
        "fragment": fragment,
        "visible_window_count": len(windows),
        "matched_titles": [window["title"] for window in matches],
    }


def find_window_process_id(title_contains: str) -> Optional[int]:
    matches = find_windows_by_title(title_contains)
    if not matches:
        return None
    matches.sort(key=lambda item: item["pid"])
    return int(matches[0]["pid"])


def find_big_picture_process_id(title_contains: str) -> Optional[int]:
    return find_window_process_id(title_contains)


def get_steamish_window_titles() -> List[str]:
    keywords = ("steam", "big picture", "fullscreen", "gamepad")
    return [title for title in get_visible_window_titles() if any(keyword in title.lower() for keyword in keywords)]


def is_big_picture_running(title_contains: str) -> bool:
    return bool(find_windows_by_title(title_contains))
