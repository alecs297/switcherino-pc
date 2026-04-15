import hashlib
import ipaddress
import socket
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


def ensure_self_signed_cert(cert_path: str, key_path: str) -> None:
    cert_file = Path(cert_path)
    key_file = Path(key_path)
    cert_file.parent.mkdir(parents=True, exist_ok=True)

    if cert_file.exists() and key_file.exists():
        return

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    common_name = socket.gethostname() or "switcherino-pc"
    subject = issuer = x509.Name(
        [
            x509.NameAttribute(NameOID.COUNTRY_NAME, "FR"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Switcherino PC"),
            x509.NameAttribute(NameOID.COMMON_NAME, common_name),
        ]
    )

    san_entries = [
        x509.DNSName("localhost"),
        x509.DNSName(common_name),
        x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
    ]

    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(timezone.utc) - timedelta(minutes=5))
        .not_valid_after(datetime.now(timezone.utc) + timedelta(days=3650))
        .add_extension(x509.SubjectAlternativeName(san_entries), critical=False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )

    key_file.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    cert_file.write_bytes(cert.public_bytes(serialization.Encoding.PEM))


def load_cert_info(cert_path: str, suggested_base_url: Optional[str]) -> dict:
    pem = Path(cert_path).read_text(encoding="utf-8")
    cert = x509.load_pem_x509_certificate(pem.encode("utf-8"))
    fingerprint = hashlib.sha256(cert.public_bytes(serialization.Encoding.DER)).hexdigest()
    return {
        "suggested_base_url": suggested_base_url,
        "sha256_fingerprint": fingerprint,
        "pem": pem,
    }
