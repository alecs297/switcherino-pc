import ctypes
import ctypes.wintypes
import json
import subprocess
import sys
import time
from typing import List, Set, Dict

# ====================== FONCTIONS EXISTANTES (inchangées) ======================
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
        if not title:
            return True

        pid = ctypes.wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        windows.append({
            "hwnd": int(hwnd),
            "pid": int(pid.value),
            "title": title,
        })
        return True

    user32.EnumWindows(enum_windows_proc, 0)
    return windows


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
        rows.append({
            "pid": int(item.get("ProcessId", 0) or 0),
            "name": str(item.get("Name", "") or ""),
            "command_line": str(item.get("CommandLine", "") or ""),
        })
    return rows


# ====================== NOUVELLE PARTIE : SURVEILLANCE ======================
def main() -> int:
    print("Surveillance des fenêtres démarrée... (Ctrl+C pour arrêter)\n")

    # On garde uniquement les titres pour détecter les changements rapidement
    previous_titles: Set[str] = set()

    try:
        while True:
            visible_windows = get_visible_windows()
            current_titles: Set[str] = {w["title"] for w in visible_windows}

            # Détection des changements
            new_windows = current_titles - previous_titles
            closed_windows = previous_titles - current_titles

            if new_windows or closed_windows:
                if new_windows:
                    for title in sorted(new_windows):
                        print(f"[+] Apparition : {title}")
                
                if closed_windows:
                    for title in sorted(closed_windows):
                        print(f"[-] Disparition : {title}")
                
                print("-" * 70)

            previous_titles = current_titles
            time.sleep(1)

    except KeyboardInterrupt:
        print("\n\nSurveillance arrêtée.")
        return 0
    except Exception as e:
        print(f"Erreur : {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())