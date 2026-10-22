"""JSON Web Key Set (JWKS) and Cryptographic Key Management for eCW SMART on FHIR.

Compliant with RFC 7517 (JSON Web Key), RFC 7519 (JSON Web Token), RFC 7523 (JWT Bearer Token),
and the SMART App Launch Framework (Client Confidential - Asymmetric / Backend Services).

eClinicalWorks specifically mandates the RS384 algorithm for asymmetric authentication.
Only public key parameters ('kty', 'use', 'alg', 'kid', 'n', 'e') are exposed via the JWKS endpoint.
Private key material is protected and never serialized or logged.
"""
import base64
import logging
import os
import time
import uuid
from typing import Any, Dict, Optional, Tuple

import jwt
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from app.core.config import settings

logger = logging.getLogger(__name__)


def _int_to_base64url(val: int) -> str:
    """Convert an integer to a standard base64url-encoded string without padding."""
    byte_length = (val.bit_length() + 7) // 8
    raw_bytes = val.to_bytes(byte_length, byteorder="big")
    return base64.urlsafe_b64encode(raw_bytes).decode("ascii").rstrip("=")


class KeyManager:
    """Manages RSA cryptographic key pair, public JWKS representation, and client assertion generation."""

    def __init__(self) -> None:
        self._private_key: Optional[rsa.RSAPrivateKey] = None
        self._public_key: Optional[rsa.RSAPublicKey] = None
        self._key_id: str = settings.ECW_KEY_ID or "ecw-key-1"
        self._load_or_generate_keys()

    def _load_or_generate_keys(self) -> None:
        """Load RSA keypair from environment secret, file system, or generate in-memory."""
        # 1. Try loading private key from environment variable string (Render Secrets)
        if settings.ECW_PRIVATE_KEY and settings.ECW_PRIVATE_KEY.strip():
            try:
                pem_data = settings.ECW_PRIVATE_KEY.strip().encode("utf-8")
                key = serialization.load_pem_private_key(pem_data, password=None)
                if isinstance(key, rsa.RSAPrivateKey):
                    self._private_key = key
                    self._public_key = key.public_key()
                    logger.info("Loaded eCW RSA private key from environment secret (bits: %d)", key.key_size)
                    return
            except Exception as exc:
                logger.error("Failed to parse ECW_PRIVATE_KEY environment secret: %s", exc)

        # 2. Try loading from file path (local development fallback)
        if settings.ECW_PRIVATE_KEY_PATH and os.path.exists(settings.ECW_PRIVATE_KEY_PATH):
            try:
                with open(settings.ECW_PRIVATE_KEY_PATH, "rb") as f:
                    pem_data = f.read()
                key = serialization.load_pem_private_key(pem_data, password=None)
                if isinstance(key, rsa.RSAPrivateKey):
                    self._private_key = key
                    self._public_key = key.public_key()
                    logger.info("Loaded eCW RSA private key from %s (bits: %d)", settings.ECW_PRIVATE_KEY_PATH, key.key_size)
                    return
            except Exception as exc:
                logger.error("Failed to load private key from %s: %s", settings.ECW_PRIVATE_KEY_PATH, exc)

        # 3. If public key file exists standalone
        if settings.ECW_PUBLIC_KEY_PATH and os.path.exists(settings.ECW_PUBLIC_KEY_PATH):
            try:
                with open(settings.ECW_PUBLIC_KEY_PATH, "rb") as f:
                    pem_data = f.read()
                pub_key = serialization.load_pem_public_key(pem_data)
                if isinstance(pub_key, rsa.RSAPublicKey):
                    self._public_key = pub_key
                    logger.info("Loaded standalone eCW RSA public key from %s", settings.ECW_PUBLIC_KEY_PATH)
            except Exception as exc:
                logger.error("Failed to load public key from %s: %s", settings.ECW_PUBLIC_KEY_PATH, exc)

        # 4. Fallback: generate ephemeral RSA 2048-bit keypair for development/test boot
        if not self._private_key:
            logger.warning(
                "No external eCW RSA private key configured. Generating ephemeral 2048-bit RSA key for development."
            )
            self._private_key = rsa.generate_private_key(
                public_exponent=65537,
                key_size=2048,
            )
            self._public_key = self._private_key.public_key()

    @property
    def key_id(self) -> str:
        return self._key_id

    def set_keys(self, private_key: rsa.RSAPrivateKey, key_id: Optional[str] = None) -> None:
        """Explicitly set keypair (useful in automated tests)."""
        self._private_key = private_key
        self._public_key = private_key.public_key()
        if key_id:
            self._key_id = key_id

    def get_public_jwk(self) -> Dict[str, Any]:
        """Return the public key formatted as an RFC 7517 JSON Web Key (JWK).

        Includes: kty, use, alg (RS384), kid, n, e.
        NEVER includes private key parameters.
        """
        if not self._public_key:
            raise RuntimeError("Public key is not initialized.")

        numbers = self._public_key.public_numbers()
        return {
            "kty": "RSA",
            "use": "sig",
            "alg": "RS384",
            "kid": self._key_id,
            "n": _int_to_base64url(numbers.n),
            "e": _int_to_base64url(numbers.e),
        }

    def get_jwks(self) -> Dict[str, Any]:
        """Return the standards-compliant JSON Web Key Set (JWKS)."""
        return {"keys": [self.get_public_jwk()]}

    def generate_client_assertion(
        self,
        client_id: Optional[str] = None,
        token_url: Optional[str] = None,
        expiry_seconds: Optional[int] = None,
    ) -> str:
        """Create and sign a client assertion JWT per SMART Backend Services / RFC 7523.

        Header:
            - alg: 'RS384' (required by eCW)
            - typ: 'JWT'
            - kid: self._key_id (matching public key in JWKS)
        Payload:
            - iss: client_id
            - sub: client_id
            - aud: token_url
            - jti: unique uuid4
            - iat: now
            - exp: now + expiry_seconds (default 300)
        """
        if not self._private_key:
            raise RuntimeError("Private key is not available to sign client assertion.")

        cid = client_id or settings.ECW_CLIENT_ID or "unconfigured-client-id"
        aud = token_url or settings.ECW_TOKEN_URL
        ttl = expiry_seconds if expiry_seconds is not None else settings.ECW_ASSERTION_EXPIRY_SECONDS

        now = int(time.time())
        claims = {
            "iss": cid,
            "sub": cid,
            "aud": aud,
            "jti": str(uuid.uuid4()),
            "iat": now,
            "exp": now + ttl,
        }
        headers = {
            "alg": "RS384",
            "typ": "JWT",
            "kid": self._key_id,
        }

        # Convert private key to PEM format in-memory for PyJWT signing
        pem_private = self._private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )

        signed_token = jwt.encode(
            payload=claims,
            key=pem_private,
            algorithm="RS384",
            headers=headers,
        )
        return signed_token


# Global singleton instance
key_manager = KeyManager()
