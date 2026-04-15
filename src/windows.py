import ctypes
import logging
import subprocess
from ctypes import wintypes


logger = logging.getLogger(__name__)


SM_REMOTESESSION = 0x1000
WTS_CURRENT_SERVER_HANDLE = wintypes.HANDLE(0)
WTS_CURRENT_SESSION = 0xFFFFFFFF
WTSClientProtocolType = 16
WTSIsRemoteSession = 29

wtsapi32 = ctypes.windll.wtsapi32


def _query_wts_value(info_class: int):
    buffer = ctypes.c_void_p()
    bytes_returned = wintypes.DWORD()
    success = wtsapi32.WTSQuerySessionInformationW(
        WTS_CURRENT_SERVER_HANDLE,
        WTS_CURRENT_SESSION,
        info_class,
        ctypes.byref(buffer),
        ctypes.byref(bytes_returned),
    )
    if not success:
        return None

    try:
        if not buffer.value:
            return None
        if info_class == WTSClientProtocolType:
            return ctypes.cast(buffer, ctypes.POINTER(wintypes.USHORT)).contents.value
        if info_class == WTSIsRemoteSession:
            return bool(ctypes.cast(buffer, ctypes.POINTER(wintypes.BOOL)).contents.value)
        return None
    finally:
        wtsapi32.WTSFreeMemory(buffer)


def is_remote_session() -> bool:
    try:
        remote_value = _query_wts_value(WTSIsRemoteSession)
        if remote_value is not None:
            return bool(remote_value)
    except Exception:
        logger.exception("Unable to query Windows remote-session state via WTSIsRemoteSession")

    try:
        protocol_type = _query_wts_value(WTSClientProtocolType)
        if protocol_type is not None:
            return int(protocol_type) == 2
    except Exception:
        logger.exception("Unable to query Windows remote-session protocol via WTSClientProtocolType")

    try:
        return bool(ctypes.windll.user32.GetSystemMetrics(SM_REMOTESESSION))
    except Exception:
        logger.exception("Unable to query Windows remote-session state via GetSystemMetrics")
        return False


def show_error_message(title: str, message: str) -> None:
    try:
        ctypes.windll.user32.MessageBoxW(0, message, title, 0x10)
    except Exception:
        logger.exception("Unable to show Windows error message box")


def show_desktop_notification(title: str, message: str) -> None:
    escaped_title = str(title or "").replace("'", "''")
    escaped_message = str(message or "").replace("'", "''")
    script = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        "Add-Type -AssemblyName System.Drawing; "
        "$notify = New-Object System.Windows.Forms.NotifyIcon; "
        "$notify.Icon = [System.Drawing.SystemIcons]::Information; "
        f"$notify.BalloonTipTitle = '{escaped_title}'; "
        f"$notify.BalloonTipText = '{escaped_message}'; "
        "$notify.Visible = $true; "
        "$notify.ShowBalloonTip(3000); "
        "Start-Sleep -Seconds 4; "
        "$notify.Dispose()"
    )
    try:
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
            startupinfo=startupinfo,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception:
        logger.exception("Unable to show desktop notification")
