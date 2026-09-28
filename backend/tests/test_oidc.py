import base64
import secrets
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.security.oidc import OidcError, OidcVerifier

AUDIENCE = "https://worker.example.run.app"
CALLER = "guiili-tasks@guiili.iam.gserviceaccount.com"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _b64(number: int) -> str:
    raw = number.to_bytes((number.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _jwks(key, kid: str = "k1") -> dict:
    numbers = key.public_key().public_numbers()
    return {"keys": [{"kty": "RSA", "kid": kid, "use": "sig", "alg": "RS256",
                      "n": _b64(numbers.n), "e": _b64(numbers.e)}]}


def _token(*, key=KEY, kid: str = "k1", **overrides) -> str:
    now = int(time.time())
    claims = {"iss": "https://accounts.google.com", "aud": AUDIENCE, "email": CALLER,
              "email_verified": True, "sub": "1234", "iat": now, "exp": now + 600}
    claims.update(overrides)
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": kid})


def _verifier(jwks: dict | None = None, calls: list | None = None) -> OidcVerifier:
    async def fetch() -> dict:
        if calls is not None:
            calls.append(1)
        return jwks or _jwks(KEY)

    return OidcVerifier(audience=AUDIENCE, allowed_emails={CALLER}, fetch_jwks=fetch)


async def test_a_valid_google_token_is_accepted_and_keys_are_cached() -> None:
    calls: list = []
    verifier = _verifier(calls=calls)
    identity = await verifier.verify(_token())
    assert identity.email == CALLER and identity.subject == "1234"
    await verifier.verify(_token())
    assert len(calls) == 1


@pytest.mark.parametrize(
    ("token_kwargs", "reason"),
    [
        ({"aud": "https://autre.run.app"}, "invalid_token"),
        ({"exp": int(time.time()) - 3600}, "invalid_token"),
        ({"iss": "https://evil.example"}, "wrong_issuer"),
        ({"email_verified": False}, "email_not_verified"),
        ({"email": "intrus@example.com"}, "caller_not_allowed"),
        ({"key": OTHER_KEY}, "invalid_token"),
        ({"kid": "inconnue"}, "unknown_key"),
    ],
)
async def test_bad_tokens_are_refused(token_kwargs: dict, reason: str) -> None:
    with pytest.raises(OidcError) as excinfo:
        await _verifier().verify(_token(**token_kwargs))
    assert excinfo.value.reason == reason


async def test_garbage_and_hs256_tokens_are_refused() -> None:
    verifier = _verifier()
    with pytest.raises(OidcError):
        await verifier.verify("pas-un-jeton")
    # Jeton « HS256 » forgé avec une clé aléatoire (jamais un secret en dur).
    forged = jwt.encode({"aud": AUDIENCE, "email": CALLER}, secrets.token_bytes(32),
                        algorithm="HS256", headers={"kid": "k1"})
    with pytest.raises(OidcError) as excinfo:
        await verifier.verify(forged)
    assert excinfo.value.reason == "invalid_token"


async def test_an_unconfigured_verifier_refuses_everything() -> None:
    verifier = OidcVerifier(audience="", allowed_emails=set(), fetch_jwks=None)  # type: ignore[arg-type]
    with pytest.raises(OidcError) as excinfo:
        await verifier.verify(_token())
    assert excinfo.value.reason == "not_configured"


async def test_unknown_key_ids_do_not_trigger_a_jwks_fetch_on_every_request() -> None:
    calls: list = []
    clock = [1000.0]

    async def fetch() -> dict:
        calls.append(1)
        return _jwks(KEY)

    verifier = OidcVerifier(
        audience=AUDIENCE, allowed_emails={CALLER}, fetch_jwks=fetch, clock=lambda: clock[0]
    )
    for _ in range(3):
        with pytest.raises(OidcError) as excinfo:
            await verifier.verify(_token(kid="inconnue"))
        assert excinfo.value.reason == "unknown_key"
    assert len(calls) == 1
    clock[0] += 31  # rotation de clé : une relecture redevient possible
    with pytest.raises(OidcError):
        await verifier.verify(_token(kid="inconnue"))
    assert len(calls) == 2
    assert (await verifier.verify(_token())).email == CALLER


async def test_jwks_failure_refuses_the_token_with_a_short_reason() -> None:
    async def fetch() -> dict:
        raise OidcError("jwks_unavailable")

    verifier = OidcVerifier(audience=AUDIENCE, allowed_emails={CALLER}, fetch_jwks=fetch)
    with pytest.raises(OidcError) as excinfo:
        await verifier.verify(_token())
    assert excinfo.value.reason == "jwks_unavailable"
