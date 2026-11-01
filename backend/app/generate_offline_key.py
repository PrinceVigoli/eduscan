import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


def main() -> None:
    key = ec.generate_private_key(ec.SECP256R1())
    der = key.private_bytes(serialization.Encoding.DER, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    print("EDUSCAN_OFFLINE_PRIVATE_KEY_DER=" + base64.urlsafe_b64encode(der).rstrip(b"=").decode("ascii"))


if __name__ == "__main__":
    main()
