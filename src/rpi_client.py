import asyncio
import hashlib
import ipaddress
import logging
import socket
import ssl
from time import monotonic
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse, urlunparse

import httpx

from .config import AppConfig, CERTS_DIR, resolve_ca_file


logger = logging.getLogger(__name__)
HTTP_TIMEOUT_SECONDS = 10.0
PIN_VERIFY_TIMEOUT_SECONDS = 10.0
RESOLUTION_CACHE_TTL_SECONDS = 300.0
RESOLUTION_ATTEMPTS = 2
SOCKET_CONNECT_TIMEOUT_SECONDS = 5.0


class RpiClient:
    def __init__(self, config: AppConfig):
        self.config = config
        self._resolved_hosts_cache: Dict[Tuple[str, int], Tuple[float, Tuple[str, ...]]] = {}

    def is_configured(self) -> bool:
        return bool(self.config.rpi_base_url.strip() and self.config.rpi_api_key.strip())

    def get_host(self) -> Optional[str]:
        parsed = urlparse(self.config.rpi_base_url.strip())
        return parsed.hostname

    async def get_status(self) -> Dict:
        if not self.is_configured():
            return {"step": "rpi_status", "skipped": True, "reason": "rpi_not_configured"}

        request_target = await self._build_request_target("/tv/status")
        await self._verify_certificate_pin_with_timeout(request_target["host"], request_target["port"], request_target["network_host"])

        async with httpx.AsyncClient(
            verify=request_target["verify"],
            timeout=HTTP_TIMEOUT_SECONDS,
            trust_env=False,
        ) as client:
            response = await client.get(
                request_target["url"],
                headers=request_target["headers"],
                extensions=request_target["extensions"],
            )
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

        request_target = await self._build_request_target("/tv/action")
        await self._verify_certificate_pin_with_timeout(request_target["host"], request_target["port"], request_target["network_host"])

        headers = dict(request_target["headers"])
        payload = {"action": action}

        async with httpx.AsyncClient(
            verify=request_target["verify"],
            timeout=HTTP_TIMEOUT_SECONDS,
            trust_env=False,
        ) as client:
            response = await client.post(
                request_target["url"],
                headers=headers,
                json=payload,
                extensions=request_target["extensions"],
            )
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

    async def _verify_certificate_pin_with_timeout(self, host: str, port: int, network_host: str) -> None:
        if not self.config.rpi_cert_fingerprint.strip():
            return

        try:
            await asyncio.wait_for(
                asyncio.to_thread(self._verify_certificate_pin_if_needed, host, port, network_host),
                timeout=PIN_VERIFY_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError as exc:
            raise RuntimeError(
                f"Timed out while verifying RPi certificate pin for {host} after {PIN_VERIFY_TIMEOUT_SECONDS:.0f}s"
            ) from exc

    def _verify_certificate_pin_if_needed(self, host: str, port: int, network_host: str) -> None:
        expected = self.config.rpi_cert_fingerprint.strip().lower()
        if not expected:
            return

        context = ssl.create_default_context()
        ca_file = self._get_usable_ca_file()
        if ca_file:
            context.load_verify_locations(ca_file)
        if not self.config.rpi_verify_tls:
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE

        with socket.create_connection((network_host, port), timeout=SOCKET_CONNECT_TIMEOUT_SECONDS) as sock:
            with context.wrap_socket(sock, server_hostname=host) as tls_sock:
                der = tls_sock.getpeercert(binary_form=True)

        actual = hashlib.sha256(der).hexdigest().lower()
        if actual != expected:
            raise RuntimeError("RPi certificate fingerprint mismatch")

    async def _build_request_target(self, path_suffix: str) -> Dict:
        parsed = urlparse(self.config.rpi_base_url.strip())
        host = parsed.hostname
        if not parsed.scheme or not host:
            raise RuntimeError("rpi_base_url is invalid")

        default_port = 443 if parsed.scheme == "https" else 80
        port = parsed.port or default_port
        network_host = await self._resolve_network_host(host, port)

        verify: str | bool = self.config.rpi_verify_tls
        ca_file = self._get_usable_ca_file()
        if self.config.rpi_verify_tls and ca_file:
            verify = ca_file

        headers = {"Authorization": "Bearer " + self.config.rpi_api_key}
        extensions: Dict[str, str] = {}

        if network_host != host:
            headers["Host"] = self._format_netloc(host, port, parsed.scheme)
            extensions["sni_hostname"] = host

        return {
            "extensions": extensions,
            "headers": headers,
            "host": host,
            "network_host": network_host,
            "port": port,
            "url": self._build_direct_url(parsed, network_host, port, path_suffix),
            "verify": verify,
        }

    async def _resolve_network_host(self, host: str, port: int) -> str:
        if self._is_ip_address(host):
            return host

        try:
            candidates = await asyncio.wait_for(
                asyncio.to_thread(self._resolve_network_hosts, host, port),
                timeout=PIN_VERIFY_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError as exc:
            raise RuntimeError(
                f"Timed out while resolving RPi host {host} after {PIN_VERIFY_TIMEOUT_SECONDS:.0f}s"
            ) from exc

        if not candidates:
            raise RuntimeError(f"Could not resolve RPi host {host}")

        return candidates[0]

    def _resolve_network_hosts(self, host: str, port: int) -> List[str]:
        cache_key = (host.lower(), port)
        cached = self._resolved_hosts_cache.get(cache_key)
        now = monotonic()
        if cached and cached[0] > now:
            return list(cached[1])

        infos = None
        last_error = None
        for attempt in range(1, RESOLUTION_ATTEMPTS + 1):
            try:
                infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
                break
            except socket.gaierror as exc:
                last_error = exc
                logger.warning(
                    "RPi host resolution failed for %s on attempt %s/%s: %s",
                    host,
                    attempt,
                    RESOLUTION_ATTEMPTS,
                    exc,
                )

        if infos is None:
            raise RuntimeError(f"Could not resolve RPi host {host}") from last_error

        ipv4_hosts: List[str] = []
        ipv6_hosts: List[str] = []
        seen = set()

        for family, _, _, _, sockaddr in infos:
            address = sockaddr[0]
            if address in seen:
                continue
            seen.add(address)
            if family == socket.AF_INET:
                ipv4_hosts.append(address)
            elif family == socket.AF_INET6:
                ipv6_hosts.append(address)

        candidates = ipv4_hosts + ipv6_hosts
        if not candidates:
            raise RuntimeError(f"Could not resolve RPi host {host}")

        self._resolved_hosts_cache[cache_key] = (now + RESOLUTION_CACHE_TTL_SECONDS, tuple(candidates))
        logger.info("Resolved RPi host %s to %s", host, ", ".join(candidates))
        return candidates

    def _build_direct_url(self, parsed, network_host: str, port: int, path_suffix: str) -> str:
        base_path = parsed.path.rstrip("/")
        path = base_path + path_suffix
        netloc = self._format_netloc(network_host, port, parsed.scheme)
        return urlunparse(parsed._replace(netloc=netloc, path=path, params="", query="", fragment=""))

    def _format_netloc(self, host: str, port: int, scheme: str) -> str:
        default_port = 443 if scheme == "https" else 80
        host_text = host
        if ":" in host and not host.startswith("["):
            host_text = f"[{host}]"
        if port == default_port:
            return host_text
        return f"{host_text}:{port}"

    def _is_ip_address(self, value: str) -> bool:
        try:
            ipaddress.ip_address(value)
        except ValueError:
            return False
        return True

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
