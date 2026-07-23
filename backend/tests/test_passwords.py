from twinlab_backend.auth.passwords import hash_password, verify_password


def test_hash_verify_roundtrip() -> None:
    h = hash_password("correct horse battery staple")
    assert h != "correct horse battery staple"  # not stored in the clear
    assert verify_password("correct horse battery staple", h)


def test_verify_rejects_wrong_password() -> None:
    h = hash_password("s3cret")
    assert not verify_password("guess", h)


def test_verify_denies_on_malformed_hash() -> None:
    # A corrupt/unknown stored hash must deny, not raise.
    assert not verify_password("anything", "not-a-real-hash")
