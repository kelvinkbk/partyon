#!/usr/bin/env python
"""Generate self-signed certificate for HTTPS and WSS."""

from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.asymmetric import rsa
from datetime import datetime, timedelta
import ipaddress
import socket

# Get local IP dynamically
def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()

local_ip = get_local_ip()
print(f"🔧 Generating certificate for IP: {local_ip}")

# Generate private key
key = rsa.generate_private_key(
    public_exponent=65537,
    key_size=2048,
    backend=default_backend()
)

# Create certificate
subject = issuer = x509.Name([
    x509.NameAttribute(NameOID.COMMON_NAME, u"PartyOn"),
])

cert = x509.CertificateBuilder().subject_name(
    subject
).issuer_name(
    issuer
).public_key(
    key.public_key()
).serial_number(
    x509.random_serial_number()
).not_valid_before(
    datetime.utcnow()
).not_valid_after(
    datetime.utcnow() + timedelta(days=365)
).add_extension(
    x509.SubjectAlternativeName([
        x509.DNSName(u"localhost"),
        x509.DNSName(u"127.0.0.1"),
        x509.DNSName(u"*.local"),
        x509.IPAddress(ipaddress.IPv4Address(u"127.0.0.1")),
        x509.IPAddress(ipaddress.IPv4Address(local_ip)),
    ]),
    critical=False,
).sign(key, hashes.SHA256(), default_backend())

# Write certificate
with open("cert.pem", "wb") as f:
    f.write(cert.public_bytes(serialization.Encoding.PEM))

# Write key
with open("key.pem", "wb") as f:
    f.write(key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption()
    ))

print("✅ Certificate generated: cert.pem, key.pem")
