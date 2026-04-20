import asyncio
import hashlib
import logging
import socket
import ssl
from pathlib import Path
from typing import Dict, Optional
from urllib.parse import urlparse

import httpx

from .config import AppConfig, CERTS_DIR, resolve_ca_file


logger = logging.getLogger(__name__)
PIN_VERIFY_TIMEOUT_SECONDS = 6.0


class RpiClient:
    def __init__(self, config: AppConfig):
        self.config = config

    def is_configured(self) -> bool:
        return bool(self.config.rpi_base_url.strip() and self.config.rpi_api_key.strip())

    def get_host(self) -> Optional[str]:
        parsed = urlparse(self.config.rpi_base_url.strip())
        return parsed.hostname

    async def get_status(self) -> Dict:
        if not self.is_configured():
            return {"step": "rpi_status", "skipped": True, "reason": "rpi_not_configured"}

        await self._verify_certificate_pin_with_timeout()
        verify = self.config.rpi_verify_tls
        ca_file = self._get_usable_ca_file()
        if self.config.rpi_verify_tls and ca_file:
            verify = ca_file

        url = self.config.rpi_base_url.rstrip("/") + "/tv/status"
        headers = {"Authorization": "Bearer " + self.config.rpi_api_key}

        async with httpx.AsyncClient(verify=verify, timeout=10.0) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            data = response.json()
            return {
                "step": "rpi_status",
                "ok": response.is_success,
                "skipped": False,
                "status_code": response.status_code,
                "body": data,
            }

    async def post_action(self, action: str) -> Dict:
        if not self.is_configured():
            return {"step": "rpi_action", "skipped": True, "reason": "rpi_not_configured"}

        await self._verify_certificate_pin_with_timeout()
        verify = self.config.rpi_verify_tls
        ca_file = self._get_usable_ca_file()
        if self.config.rpi_verify_tls and ca_file:
            verify = ca_file

        url = self.config.rpi_base_url.rstrip("/") + "/tv/action"
        headers = {"Authorization": "Bearer " + self.config.rpi_api_key}
        payload = {"action": action}

        async with httpx.AsyncClient(verify=verify, timeout=10.0) as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
            logger.info("RPi action %s completed", action)
            return {
                "step": "rpi_action",
                "skipped": False,
                "action": action,
                "status_code": response.status_code,
                "body": data,
            }

    async def _verify_certificate_pin_with_timeout(self) -> None:
        try:
            await asyncio.wait_for(
                asyncio.to_thread(self._verify_certificate_pin_if_needed),
                timeout=PIN_VERIFY_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError as exc:
            host = self.get_host() or "<unknown-host>"
            raise RuntimeError(
                f"Timed out while verifying RPi certificate pin for {host} after {PIN_VERIFY_TIMEOUT_SECONDS:.0f}s"
            ) from exc

    def _verify_certificate_pin_if_needed(self) -> None:
        expected = self.config.rpi_cert_fingerprint.strip().lower()
        if not expected:
            return

        parsed = urlparse(self.config.rpi_base_url)
        host = parsed.hostname
        port = parsed.port or 443
        if not host:
            raise RuntimeError("rpi_base_url is invalid")

        context = ssl.create_default_context()
        ca_file = self._get_usable_ca_file()
        if ca_file:
            context.load_verify_locations(ca_file)
        if not self.config.rpi_verify_tls:
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE

        with socket.create_connection((host, port), timeout=5.0) as sock:
            with context.wrap_socket(sock, server_hostname=host) as tls_sock:
                der = tls_sock.getpeercert(binary_form=True)

        actual = hashlib.sha256(der).hexdigest().lower()
        if actual != expected:
            raise RuntimeError("RPi certificate fingerprint mismatch")

    def _get_usable_ca_file(self) -> Optional[str]:
        ca_file = resolve_ca_file(self.config.rpi_ca_file)
        if not ca_file:
            return None

        path = Path(ca_file)
        if not path.exists():
            return ca_file

        data = path.read_bytes()
        if not data.startswith(b"\xef\xbb\xbf"):
            return ca_file

        logger.warning("RPi CA file contains a UTF-8 BOM, creating a sanitized copy: %s", path)
        sanitized_path = CERTS_DIR / (path.stem + ".sanitized" + path.suffix)
        sanitized_path.write_bytes(data[3:])
        return str(sanitized_path)
