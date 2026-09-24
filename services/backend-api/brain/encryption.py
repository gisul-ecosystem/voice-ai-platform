"""Field-level symmetric encryption for PII at rest.

Guardrail: GUARDRAIL_FIELD_ENCRYPTION (default ON).
When ON, sensitive text fields (transcript turns, resume text, answer transcripts)
are encrypted with Fernet (AES-128-CBC + HMAC-SHA256) before being written to MongoDB
and decrypted on read.

Key management:
  - Set FIELD_ENCRYPTION_KEY to a URL-safe base64-encoded 32-byte key.
  - Generate a key with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
  - If the env var is absent, a per-process random key is generated and a WARNING is logged.
    In that mode, data is encrypted but NOT persistent across restarts (use only for dev).
  - Rotating keys: set FIELD_ENCRYPTION_KEY_PREV to the old key. The decrypt path
    tries the primary key first, then the previous key. The write path always uses
    the primary key.

Config flag: GUARDRAIL_FIELD_ENCRYPTION (env, default ON).
"""
from __future__ import annotations

import base64
import logging
import os

logger = logging.getLogger("backend-api.encryption")

# ---------------------------------------------------------------------------
# Config flag
# ---------------------------------------------------------------------------

def _flag(name: str, default: bool = True) -> bool:
    val = os.getenv(name, "").strip().lower()
    if not val:
        return default
    return val not in {"0", "false", "off", "no"}


GUARDRAIL_FIELD_ENCRYPTION: bool = _flag("GUARDRAIL_FIELD_ENCRYPTION")

# Prefix stamped on every ciphertext so we can detect encrypted vs. plaintext.
_ENC_PREFIX = "enc:v1:"

# ---------------------------------------------------------------------------
# Key loading
# ---------------------------------------------------------------------------

def _load_fernet():
    """Import Fernet lazily so the module loads even if cryptography isn't installed."""
    try:
        from cryptography.fernet import Fernet, MultiFernet, InvalidToken
        return Fernet, MultiFernet, InvalidToken
    except ImportError:
        logger.warning(
            "guardrail_encryption_unavailable",
            extra={
                "event": "guardrail_encryption_unavailable",
                "guardrail": "GUARDRAIL_FIELD_ENCRYPTION",
                "reason": "cryptography package not installed",
            },
        )
        return None, None, None


_fernet_instance = None  # lazy singleton


def _get_fernet():
    """Return a MultiFernet instance, creating it once per process."""
    global _fernet_instance
    if _fernet_instance is not None:
        return _fernet_instance

    Fernet, MultiFernet, _ = _load_fernet()
    if Fernet is None:
        return None

    primary_key_raw = os.getenv("FIELD_ENCRYPTION_KEY", "").strip()
    if not primary_key_raw:
        # Generate a per-process key. Data encrypted with it won't survive a restart.
        # This is intentionally allowed in development; production must set the env var.
        generated = Fernet.generate_key()
        logger.warning(
            "guardrail_encryption_ephemeral_key",
            extra={
                "event": "guardrail_encryption_ephemeral_key",
                "guardrail": "GUARDRAIL_FIELD_ENCRYPTION",
                "reason": "FIELD_ENCRYPTION_KEY not set — using ephemeral key (dev only)",
            },
        )
        primary_key_raw = generated.decode()

    # Validate and load primary key.
    try:
        primary = Fernet(primary_key_raw.encode())
    except Exception as exc:
        logger.error(
            "guardrail_encryption_bad_key",
            extra={
                "event": "guardrail_encryption_bad_key",
                "guardrail": "GUARDRAIL_FIELD_ENCRYPTION",
                "error": str(exc),
            },
        )
        return None

    fernets = [primary]

    # Optional previous key for rotation.
    prev_key_raw = os.getenv("FIELD_ENCRYPTION_KEY_PREV", "").strip()
    if prev_key_raw:
        try:
            fernets.append(Fernet(prev_key_raw.encode()))
        except Exception:
            logger.warning(
                "guardrail_encryption_bad_prev_key",
                extra={"event": "guardrail_encryption_bad_prev_key"},
            )

    _fernet_instance = MultiFernet(fernets)
    logger.info(
        "guardrail_encryption_ready",
        extra={
            "event": "guardrail_encryption_ready",
            "guardrail": "GUARDRAIL_FIELD_ENCRYPTION",
            "key_rotation_enabled": len(fernets) > 1,
        },
    )
    return _fernet_instance


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def encrypt_field(plaintext: str | None) -> str | None:
    """Encrypt a string field for storage in MongoDB.

    Returns None if the input is None.
    Returns the plaintext unchanged if GUARDRAIL_FIELD_ENCRYPTION is OFF
    or if the cryptography library is unavailable.
    Idempotent: already-encrypted values (prefixed with _ENC_PREFIX) are
    returned as-is so double-encrypt cannot happen.
    """
    if not plaintext:
        return plaintext
    if not GUARDRAIL_FIELD_ENCRYPTION:
        return plaintext
    if plaintext.startswith(_ENC_PREFIX):
        # Already encrypted — do not double-encrypt.
        return plaintext

    fernet = _get_fernet()
    if fernet is None:
        return plaintext

    try:
        token = fernet.encrypt(plaintext.encode("utf-8"))
        return _ENC_PREFIX + token.decode("ascii")
    except Exception as exc:
        logger.error(
            "guardrail_encryption_encrypt_failed",
            extra={
                "event": "guardrail_encryption_encrypt_failed",
                "guardrail": "GUARDRAIL_FIELD_ENCRYPTION",
                "error": str(exc),
            },
        )
        # Fail open: store plaintext rather than lose data.
        return plaintext


def decrypt_field(ciphertext: str | None) -> str | None:
    """Decrypt a field previously encrypted by encrypt_field.

    Returns None if the input is None.
    Returns plaintext unchanged if it was never encrypted (no prefix).
    Returns plaintext unchanged if GUARDRAIL_FIELD_ENCRYPTION is OFF.
    """
    if not ciphertext:
        return ciphertext
    if not ciphertext.startswith(_ENC_PREFIX):
        # Stored before encryption was enabled — return as-is.
        return ciphertext

    _, _, InvalidToken = _load_fernet()
    if InvalidToken is None:
        return ciphertext

    fernet = _get_fernet()
    if fernet is None:
        return ciphertext

    token_str = ciphertext[len(_ENC_PREFIX):]
    try:
        return fernet.decrypt(token_str.encode("ascii")).decode("utf-8")
    except Exception as exc:
        logger.error(
            "guardrail_encryption_decrypt_failed",
            extra={
                "event": "guardrail_encryption_decrypt_failed",
                "guardrail": "GUARDRAIL_FIELD_ENCRYPTION",
                "error": str(exc),
            },
        )
        # Return the ciphertext on failure — callers must handle sentinel values.
        return ciphertext


def is_encrypted(value: str | None) -> bool:
    """True if the value was encrypted by encrypt_field."""
    return isinstance(value, str) and value.startswith(_ENC_PREFIX)
