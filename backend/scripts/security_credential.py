"""Build Daraja's SecurityCredential: the initiator password encrypted with Safaricom's
certificate (RSA, PKCS#1 v1.5), base64. Run it yourself; the password is typed, never stored.

  docker compose exec api python scripts/security_credential.py scripts/SandboxCertificate.cer

Paste the printed line into backend/.env as DARAJA_SECURITY_CREDENTIAL=... (no quotes).
"""

import base64
import getpass
import sys

from cryptography import x509
from cryptography.hazmat.primitives.asymmetric import padding


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("usage: security_credential.py <certificate file>")
    data = open(sys.argv[1], "rb").read()
    try:
        cert = x509.load_pem_x509_certificate(data)
    except ValueError:
        cert = x509.load_der_x509_certificate(data)
    password = getpass.getpass("Initiator password (hidden): ").encode()
    token = cert.public_key().encrypt(password, padding.PKCS1v15())
    print(base64.b64encode(token).decode())


if __name__ == "__main__":
    main()
