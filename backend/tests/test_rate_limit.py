import pytest
from fastapi import HTTPException

from app.security import rate_limit
from app.security.rate_limit import SlidingWindowLimiter, client_ip, enforce


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_allows_up_to_the_limit_then_blocks_with_retry_after() -> None:
    clock = _Clock()
    limiter = SlidingWindowLimiter(clock=clock)
    for _ in range(3):
        assert limiter.check("k", limit=3, window=60) == 0.0
        clock.now += 1
    retry = limiter.check("k", limit=3, window=60)
    assert 56 <= retry <= 58  # première requête à t=1000, fenêtre 60 s, now=1003


def test_window_expiry_frees_the_key() -> None:
    clock = _Clock()
    limiter = SlidingWindowLimiter(clock=clock)
    limiter.check("k", limit=1, window=10)
    assert limiter.check("k", limit=1, window=10) > 0
    clock.now += 11
    assert limiter.check("k", limit=1, window=10) == 0.0


def test_keys_are_independent_and_peek_does_not_record() -> None:
    limiter = SlidingWindowLimiter(clock=_Clock())
    limiter.check("a", limit=1, window=60)
    assert limiter.check("b", limit=1, window=60) == 0.0
    for _ in range(5):
        assert limiter.retry_after("c", limit=1, window=60) == 0.0
    limiter.record("c")
    assert limiter.retry_after("c", limit=1, window=60) > 0


def test_reset_clears_everything() -> None:
    limiter = SlidingWindowLimiter(clock=_Clock())
    limiter.check("k", limit=1, window=60)
    limiter.reset()
    assert limiter.check("k", limit=1, window=60) == 0.0


def test_expired_keys_are_collected_when_the_table_is_full() -> None:
    clock = _Clock()
    limiter = SlidingWindowLimiter(clock=clock, max_keys=100)
    for i in range(90):
        limiter.check(f"old{i}", limit=5, window=60)
    clock.now += 120  # toutes les clés précédentes ont expiré
    for i in range(20):
        limiter.check(f"new{i}", limit=5, window=60)
    # Le ramasse-miettes s'est déclenché au 101e passage : seules les récentes restent.
    assert len(limiter._hits) <= 21
    assert "old0" not in limiter._hits


def test_saturation_by_distinct_keys_never_grows_without_bound() -> None:
    limiter = SlidingWindowLimiter(clock=_Clock(), max_keys=100)
    for i in range(500):
        limiter.check(f"attack{i}", limit=5, window=60)
    assert len(limiter._hits) <= 101


def test_enforce_raises_429_with_retry_after_header() -> None:
    limiter_key = "test-enforce-429"
    enforce(limiter_key, limit=1, window=60)
    with pytest.raises(HTTPException) as excinfo:
        enforce(limiter_key, limit=1, window=60)
    assert excinfo.value.status_code == 429
    assert int(excinfo.value.headers["Retry-After"]) >= 1


def test_enforce_can_be_disabled() -> None:
    for _ in range(5):
        enforce("test-disabled", limit=1, window=60, enabled=False)


def test_client_ip_prefers_the_first_forwarded_address() -> None:
    class _Req:
        def __init__(self, headers: dict, host: str | None) -> None:
            self.headers = headers
            self.client = type("C", (), {"host": host})() if host else None

    assert client_ip(_Req({"x-forwarded-for": "203.0.113.5, 10.0.0.1"}, "10.0.0.1")) == "203.0.113.5"
    assert client_ip(_Req({}, "192.0.2.7")) == "192.0.2.7"
    assert client_ip(_Req({}, None)) == "unknown"


def test_ip_flood_does_not_reset_email_lockouts(monkeypatch) -> None:
    monkeypatch.setattr(rate_limit.ip_limiter, "_max_keys", 50)
    # Verrou par e-mail (10 échecs enregistrés, comme la route de login).
    for _ in range(10):
        rate_limit.identity_limiter.record("login_failures:email:victime@example.com")
    assert rate_limit.identity_limiter.retry_after(
        "login_failures:email:victime@example.com", limit=10, window=900
    ) > 0
    # Inondation d'IP forgées : la saturation du compteur d'IP vide SON stockage seulement.
    for i in range(500):
        rate_limit.enforce(
            f"login:ip:10.0.{i // 250}.{i % 250}", limit=30, window=900, store=rate_limit.ip_limiter
        )
    assert len(rate_limit.ip_limiter._hits) <= 51
    with pytest.raises(HTTPException) as excinfo:
        rate_limit.enforce_not_blocked(
            "login_failures:email:victime@example.com", limit=10, window=900
        )
    assert excinfo.value.status_code == 429
