from app.api.auth import hash_password, verify_password


def test_hash_and_verify_password():
    hashed = hash_password("my-secret-password")

    assert isinstance(hashed, str)
    assert hashed != "my-secret-password"
    assert verify_password("my-secret-password", hashed) is True
    assert verify_password("wrong-password", hashed) is False
