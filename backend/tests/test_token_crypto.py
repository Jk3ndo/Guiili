import base64
import os
from typing import ClassVar

import pytest
from pydantic import SecretStr

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
    token = c.encrypt("1//refresh-token-secret", aad=None)
    assert isinstance(token, EncryptedToken)
    assert token.key_version == 1
    assert c.decrypt(token, aad=None) == "1//refresh-token-secret"


def test_encrypt_uses_active_version() -> None:
    token = cipher(active=2).encrypt("x", aad=None)
    assert token.key_version == 2


def test_pack_unpack_survives_round_trip() -> None:
    c = cipher()
    token = c.encrypt("secret-value", aad=None)
    blob = token.pack()
    restored = EncryptedToken.unpack(blob)
    assert restored == token
    assert c.decrypt(restored, aad=None) == "secret-value"


def test_nonce_is_unique_per_encryption() -> None:
    c = cipher()
    nonces = {c.encrypt("same", aad=None).nonce for _ in range(50)}
    assert len(nonces) == 50


def test_tampered_ciphertext_raises() -> None:
    c = cipher()
    token = c.encrypt("secret", aad=None)
    tampered = EncryptedToken(
        ciphertext=bytes([token.ciphertext[0] ^ 0x01]) + token.ciphertext[1:],
        nonce=token.nonce,
        key_version=token.key_version,
    )
    with pytest.raises(TokenDecryptionError):
        c.decrypt(tampered, aad=None)


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
        c.decrypt(token, aad=None)


def test_malformed_nonce_raises_decryption_error() -> None:
    c = cipher()
    token = EncryptedToken(ciphertext=b"x" * 32, nonce=b"short", key_version=1)
    with pytest.raises(TokenDecryptionError):
        c.decrypt(token, aad=None)


def test_rotate_reencrypts_to_active_version() -> None:
    old = TokenCipher(keys={1: KEY_V1, 2: KEY_V2}, active_version=1)
    token_v1 = old.encrypt("secret", aad=None)
    new = TokenCipher(keys={1: KEY_V1, 2: KEY_V2}, active_version=2)
    token_v2 = new.rotate(token_v1, aad=None)
    assert token_v2.key_version == 2
    assert new.decrypt(token_v2, aad=None) == "secret"
    # l'ancien token reste déchiffrable tant que la clé v1 est dans le registre
    assert new.decrypt(token_v1, aad=None) == "secret"


def test_rejects_out_of_range_version() -> None:
    with pytest.raises(TokenCryptoConfigError):
        TokenCipher(keys={70000: KEY_V1}, active_version=70000)


def test_golden_blob_layout() -> None:
    """Le format sur le fil est stable : 2 octets version || 12 nonce || >=16 tag."""
    blob = cipher().encrypt("x", aad=None).pack()
    assert blob[:2] == b"\x00\x01"
    assert len(blob) >= 2 + 12 + 16


def test_golden_decrypt_hardcoded_triple() -> None:
    """Déchiffre un triplet (version, clé, blob) figé : détecte tout changement de format."""
    key = base64.b64decode("AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8=")
    blob = bytes.fromhex(
        "0001"
        "000102030405060708090a0b"
        "206dba7fa08bef69e827e5eec2815519ecbde25ad374262f1702d9bf765d7fd7a096e568"
    )
    c = TokenCipher(keys={1: key}, active_version=1)
    token = EncryptedToken.unpack(blob)
    assert token.key_version == 1
    assert c.decrypt(token, aad=None) == "golden-refresh-token"


def test_load_from_settings() -> None:
    # Valeurs en SecretStr, comme la vraie classe Settings.
    class FakeSettings:
        token_enc_keys: ClassVar = {
            1: SecretStr(base64.b64encode(KEY_V1).decode()),
            2: SecretStr(base64.b64encode(KEY_V2).decode()),
        }
        token_enc_active_version = 2

    c = load_token_cipher(FakeSettings())
    assert c.decrypt(c.encrypt("hello", aad=None), aad=None) == "hello"


def test_encrypted_token_repr_hides_bytes() -> None:
    token = cipher().encrypt("super-secret-refresh-token", aad=None)
    r = repr(token)
    assert "ciphertext=<" in r and "nonce=<" in r
    # ni le plaintext ni les octets bruts ne doivent apparaître
    assert "super-secret-refresh-token" not in r
    assert repr(token.ciphertext) not in r
    assert repr(token.nonce) not in r


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


def test_load_rejects_non_integer_version() -> None:
    class FakeSettings:
        token_enc_keys: ClassVar = {"abc": base64.b64encode(KEY_V1).decode()}
        token_enc_active_version = 1

    with pytest.raises(TokenCryptoConfigError, match="version non entière"):
        load_token_cipher(FakeSettings())
