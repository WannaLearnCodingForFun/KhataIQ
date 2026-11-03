from khataiq.security import hash_password, verify_password


def test_hash_verifies_and_is_salted():
    first, second = hash_password("s3cret"), hash_password("s3cret")
    assert first != second  # random salt per hash
    assert verify_password(first, "s3cret") and verify_password(second, "s3cret")


def test_wrong_password_and_garbage_hash_are_false_not_errors():
    h = hash_password("s3cret")
    assert not verify_password(h, "S3cret")
    assert not verify_password("not-a-hash", "s3cret")
