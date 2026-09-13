from app.security.password import hash_password, verify_password


def test_hash_password_verifies_correctly() -> None:
    hashed = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", hashed) is True


def test_verify_password_rejects_wrong_password() -> None:
    hashed = hash_password("correct horse battery staple")
    assert verify_password("wrong password", hashed) is False


def test_hash_password_is_not_plaintext() -> None:
    hashed = hash_password("secret")
    assert "secret" not in hashed


def test_verify_password_rejects_malformed_hash() -> None:
    # Un hash corrompu/vide ne doit jamais lever, juste renvoyer False.
    assert verify_password("secret", "not-a-real-hash") is False
