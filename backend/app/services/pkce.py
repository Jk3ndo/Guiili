from __future__ import annotations

import base64
import hashlib
import secrets


def generate_pkce_pair() -> tuple[str, str]:
    """Retourne ``(code_verifier, code_challenge)`` pour PKCE S256.

    Le verifier fait ~86 caracteres URL-safe (RFC 7636 : 43-128).
    """
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def verify_pkce(code_verifier: str, code_challenge: str) -> bool:
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    expected = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return secrets.compare_digest(expected, code_challenge)
