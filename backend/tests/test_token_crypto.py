import base64
import os
from typing import ClassVar

import pytest

from app.security.token_crypto import (
    EncryptedToken,
    TokenCipher,
    TokenCryptoConfigError,
    TokenDecryptionError,
    UnknownKeyVersionError,
    load_token_cipher,
)

KEY_V1 = os.urandom(32)
KEY_V2 = os.urandom(32)


def cipher(active: int = 1) -> TokenCipher:
    return TokenCipher(keys={1: KEY_V1, 2: KEY_V2}, active_version=active)


def test_round_trip() -> None:
    c = cipher()
    token = c.encrypt("1//refresh-token-secret")
    assert isinstance(token, EncryptedToken)
    assert token.key_version == 1
    assert c.decrypt(token) == "1//refresh-token-secret"


def test_encrypt_uses_active_version() -> None:
    token = cipher(active=2).encrypt("x")
    assert token.key_version == 2


def test_pack_unpack_survives_round_trip() -> None:
    c = cipher()
    token = c.encrypt("secret-value")
    blob = token.pack()
    restored = EncryptedToken.unpack(blob)
    assert restored == token
    assert c.decrypt(restored) == "secret-value"


def test_nonce_is_unique_per_encryption() -> None:
    c = cipher()
    nonces = {c.encrypt("same").nonce for _ in range(50)}
    assert len(nonces) == 50


def test_tampered_ciphertext_raises() -> None:
    c = cipher()
    token = c.encrypt("secret")
    tampered = EncryptedToken(
        ciphertext=bytes([token.ciphertext[0] ^ 0x01]) + token.ciphertext[1:],
        nonce=token.nonce,
        key_version=token.key_version,
    )
    with pytest.raises(TokenDecryptionError):
        c.decrypt(tampered)


def test_aad_mismatch_raises() -> None:
    c = cipher()
    token = c.encrypt("secret", aad=b"user-123")
    with pytest.raises(TokenDecryptionError):
        c.decrypt(token, aad=b"user-999")
    assert c.decrypt(token, aad=b"user-123") == "secret"


def test_unknown_key_version_raises() -> None:
    c = cipher()
    token = EncryptedToken(ciphertext=b"x" * 20, nonce=b"y" * 12, key_version=99)
    with pytest.raises(UnknownKeyVersionError):
        c.decrypt(token)


def test_rotate_reencrypts_to_active_version() -> None:
    old = TokenCipher(keys={1: KEY_V1, 2: KEY_V2}, active_version=1)
    token_v1 = old.encrypt("secret")
    new = TokenCipher(keys={1: KEY_V1, 2: KEY_V2}, active_version=2)
    token_v2 = new.rotate(token_v1)
    assert token_v2.key_version == 2
    assert new.decrypt(token_v2) == "secret"
    # l'ancien token reste déchiffrable tant que la clé v1 est dans le registre
    assert new.decrypt(token_v1) == "secret"


def test_load_from_settings(monkeypatch) -> None:
    class FakeSettings:
        token_enc_keys: ClassVar = {
            1: base64.b64encode(KEY_V1).decode(),
            2: base64.b64encode(KEY_V2).decode(),
        }
        token_enc_active_version = 2

    c = load_token_cipher(FakeSettings())
    assert c.decrypt(c.encrypt("hello")) == "hello"


def test_load_rejects_short_key() -> None:
    class FakeSettings:
        token_enc_keys: ClassVar = {1: base64.b64encode(b"tooshort").decode()}
        token_enc_active_version = 1

    with pytest.raises(TokenCryptoConfigError):
        load_token_cipher(FakeSettings())


def test_load_rejects_missing_active_version() -> None:
    class FakeSettings:
        token_enc_keys: ClassVar = {1: base64.b64encode(KEY_V1).decode()}
        token_enc_active_version = 5

    with pytest.raises(TokenCryptoConfigError):
        load_token_cipher(FakeSettings())
