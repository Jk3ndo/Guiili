from __future__ import annotations

import base64
import os
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_VERSION_BYTES = 2
_NONCE_BYTES = 12
_KEY_BYTES = 32
_BYTE_ORDER = "big"


class TokenCryptoError(Exception):
    """Base de toutes les erreurs de ce module."""


class TokenDecryptionError(TokenCryptoError):
    """Authentification GCM échouée : blob corrompu, mauvaise clé, ou AAD incorrecte."""


class UnknownKeyVersionError(TokenCryptoError):
    """La version de clé du token n'est pas dans le registre."""


class TokenCryptoConfigError(TokenCryptoError):
    """Configuration d'environnement invalide."""


@dataclass(frozen=True)
class EncryptedToken:
    ciphertext: bytes
    nonce: bytes
    key_version: int

    def pack(self) -> bytes:
        return (
            self.key_version.to_bytes(_VERSION_BYTES, _BYTE_ORDER)
            + self.nonce
            + self.ciphertext
        )

    @classmethod
    def unpack(cls, blob: bytes) -> EncryptedToken:
        if len(blob) < _VERSION_BYTES + _NONCE_BYTES:
            raise TokenDecryptionError("blob trop court")
        version = int.from_bytes(blob[:_VERSION_BYTES], _BYTE_ORDER)
        nonce = blob[_VERSION_BYTES : _VERSION_BYTES + _NONCE_BYTES]
        ciphertext = blob[_VERSION_BYTES + _NONCE_BYTES :]
        return cls(ciphertext=ciphertext, nonce=nonce, key_version=version)


_MAX_VERSION = 1 << (_VERSION_BYTES * 8)  # 65536 : la version tient sur 2 octets


class TokenCipher:
    def __init__(self, keys: dict[int, bytes], active_version: int) -> None:
        if active_version not in keys:
            raise TokenCryptoConfigError(
                f"version active {active_version} absente du registre de clés"
            )
        for version, key in keys.items():
            if not 0 <= version < _MAX_VERSION:
                raise TokenCryptoConfigError(
                    f"version de clé {version} hors plage [0, {_MAX_VERSION})"
                )
            if len(key) != _KEY_BYTES:
                raise TokenCryptoConfigError(
                    f"la clé v{version} fait {len(key)} octets, {_KEY_BYTES} attendus"
                )
        self._keys = dict(keys)
        self._active_version = active_version

    def _aesgcm(self, version: int) -> AESGCM:
        try:
            key = self._keys[version]
        except KeyError as exc:
            raise UnknownKeyVersionError(f"version de clé inconnue : {version}") from exc
        return AESGCM(key)

    def encrypt(self, plaintext: str, *, aad: bytes | None) -> EncryptedToken:
        nonce = os.urandom(_NONCE_BYTES)
        ciphertext = self._aesgcm(self._active_version).encrypt(
            nonce, plaintext.encode("utf-8"), aad
        )
        return EncryptedToken(
            ciphertext=ciphertext, nonce=nonce, key_version=self._active_version
        )

    def decrypt(self, token: EncryptedToken, *, aad: bytes | None) -> str:
        aesgcm = self._aesgcm(token.key_version)
        try:
            plaintext = aesgcm.decrypt(token.nonce, token.ciphertext, aad)
        except InvalidTag as exc:
            raise TokenDecryptionError(
                "échec d'authentification du token chiffré"
            ) from exc
        except ValueError as exc:
            # nonce de longueur invalide, etc. — cryptography lève ValueError
            raise TokenDecryptionError(f"blob chiffré malformé : {exc}") from exc
        return plaintext.decode("utf-8")

    def rotate(
        self, token: EncryptedToken, *, aad: bytes | None
    ) -> EncryptedToken:
        plaintext = self.decrypt(token, aad=aad)
        return self.encrypt(plaintext, aad=aad)


def load_token_cipher(settings: object) -> TokenCipher:
    raw_keys: dict[int, str] = settings.token_enc_keys
    active_version: int = settings.token_enc_active_version
    decoded: dict[int, bytes] = {}
    for version, b64 in raw_keys.items():
        try:
            int_version = int(version)
        except (ValueError, TypeError) as exc:
            raise TokenCryptoConfigError(
                f"clé v{version}: version non entière"
            ) from exc
        try:
            decoded[int_version] = base64.b64decode(b64, validate=True)
        except (ValueError, TypeError) as exc:
            raise TokenCryptoConfigError(
                f"clé v{version} : base64 invalide"
            ) from exc
    return TokenCipher(keys=decoded, active_version=active_version)
