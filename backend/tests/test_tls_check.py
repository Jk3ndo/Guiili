"""Verification de certificat : classification pure + wrapper avec probe injecte."""

from datetime import UTC, datetime, timedelta

from app.services.tls_check import TlsProbe, check_certificate, classify_certificate

_NOW = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)


def _cert(not_after: datetime, issuer: str = "Let's Encrypt") -> dict:
    return {
        "notAfter": not_after.strftime("%b %d %H:%M:%S %Y GMT"),
        "issuer": ((("organizationName", issuer),),),
    }


def _probe(**kw) -> TlsProbe:
    base = {"cert": None, "verified": False, "verify_error": None, "transport_error": None}
    return TlsProbe(**{**base, **kw})


def test_valid_certificate() -> None:
    probe = _probe(cert=_cert(_NOW + timedelta(days=70)), verified=True)
    status = classify_certificate("x.fr", probe, now=_NOW)
    assert status.status == "valid"
    assert status.days_remaining == 70
    assert status.issuer == "Let's Encrypt"


def test_expiring_soon() -> None:
    probe = _probe(cert=_cert(_NOW + timedelta(days=12)), verified=True)
    status = classify_certificate("x.fr", probe, now=_NOW)
    assert status.status == "expiring_soon"
    assert status.days_remaining == 12


def test_expired_even_if_dates_recovered_unverified() -> None:
    probe = _probe(
        cert=_cert(_NOW - timedelta(days=4)),
        verified=False,
        verify_error="certificate has expired",
    )
    status = classify_certificate("x.fr", probe, now=_NOW)
    assert status.status == "expired"
    assert status.days_remaining == -4
    assert status.expires_at is not None


def test_hostname_mismatch() -> None:
    probe = _probe(
        cert=_cert(_NOW + timedelta(days=200)),
        verified=False,
        verify_error="Hostname mismatch, certificate is not valid for 'x.fr'",
    )
    assert classify_certificate("x.fr", probe, now=_NOW).status == "hostname_mismatch"


def test_self_signed() -> None:
    probe = _probe(
        cert=_cert(_NOW + timedelta(days=200)),
        verified=False,
        verify_error="self-signed certificate",
    )
    assert classify_certificate("x.fr", probe, now=_NOW).status == "self_signed"


def test_untrusted_unknown_reason() -> None:
    probe = _probe(
        cert=_cert(_NOW + timedelta(days=200)),
        verified=False,
        verify_error="unable to get local issuer certificate",
    )
    assert classify_certificate("x.fr", probe, now=_NOW).status == "untrusted"


def test_unreachable() -> None:
    probe = _probe(transport_error="Connection refused")
    status = classify_certificate("x.fr", probe, now=_NOW)
    assert status.status == "unreachable"
    assert status.error == "Connection refused"


async def test_check_certificate_uses_injected_probe() -> None:
    async def fake_probe(host: str, port: int, timeout: float) -> TlsProbe:
        _ = (port, timeout)
        assert host == "boutique.example"  # www. retire
        return _probe(cert=_cert(_NOW + timedelta(days=5)), verified=True)

    status = await check_certificate("www.Boutique.Example", now=_NOW, probe=fake_probe)
    assert status.host == "boutique.example"
    assert status.status == "expiring_soon"


async def test_check_certificate_never_raises() -> None:
    async def boom(host: str, port: int, timeout: float) -> TlsProbe:
        raise RuntimeError("socket exploded")

    status = await check_certificate("x.fr", now=_NOW, probe=boom)
    assert status.status == "unreachable"
    assert "socket exploded" in (status.error or "")
