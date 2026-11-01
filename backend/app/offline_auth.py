import base64
import hashlib
import json

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature, encode_dss_signature

from .config import settings


P256_ORDER = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _private_key() -> ec.EllipticCurvePrivateKey:
    if settings.offline_private_key_der:
        encoded = settings.offline_private_key_der + "=" * (-len(settings.offline_private_key_der) % 4)
        key = serialization.load_der_private_key(base64.urlsafe_b64decode(encoded), password=None)
        if not isinstance(key, ec.EllipticCurvePrivateKey) or not isinstance(key.curve, ec.SECP256R1):
            raise RuntimeError("Offline authorization key must be a P-256 private key")
        return key
    scalar = int.from_bytes(hashlib.sha256(settings.offline_signing_key.encode()).digest(), "big") % (P256_ORDER - 1) + 1
    return ec.derive_private_key(scalar, ec.SECP256R1())


def canonical(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


def sign(payload: dict) -> str:
    der = _private_key().sign(canonical(payload), ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der)
    return _b64url(r.to_bytes(32, "big") + s.to_bytes(32, "big"))


def verify(payload: dict, signature: str) -> bool:
    try:
        raw = base64.urlsafe_b64decode(signature + "=" * (-len(signature) % 4))
        if len(raw) != 64:
            return False
        der = encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big"))
        _private_key().public_key().verify(der, canonical(payload), ec.ECDSA(hashes.SHA256()))
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False


def public_jwk() -> dict:
    numbers = _private_key().public_key().public_numbers()
    return {"kty": "EC", "crv": "P-256", "x": _b64url(numbers.x.to_bytes(32, "big")), "y": _b64url(numbers.y.to_bytes(32, "big")), "ext": True, "key_ops": ["verify"]}
