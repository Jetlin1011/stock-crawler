"""One-time: generate VAPID keys for web-push notifications.

    python -m scanner.vapid

Copy the PRIVATE key into a GitHub *secret* VAPID_PRIVATE_KEY and the PUBLIC key into a GitHub *variable*
VAPID_PUBLIC_KEY. Never share the private key.
"""
import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


def b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def generate():
    key = ec.generate_private_key(ec.SECP256R1())
    priv = key.private_bytes(serialization.Encoding.DER, serialization.PrivateFormat.PKCS8,
                             serialization.NoEncryption())
    pub = key.public_key().public_bytes(serialization.Encoding.X962,
                                        serialization.PublicFormat.UncompressedPoint)
    return b64u(priv), b64u(pub)


if __name__ == "__main__":
    priv, pub = generate()
    print("VAPID_PRIVATE_KEY (GitHub secret):\n" + priv + "\n")
    print("VAPID_PUBLIC_KEY (GitHub variable):\n" + pub)
