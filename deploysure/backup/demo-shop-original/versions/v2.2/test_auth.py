import auth


def test_password_roundtrip():
    assert auth.verify_password("secret", auth.hash_password("secret"))


def test_wrong_password_rejected():
    assert not auth.verify_password("nope", auth.hash_password("secret"))


def test_token_valid_and_invalid():
    assert auth.is_valid_token(auth.make_token("manc"))
    assert not auth.is_valid_token("bad")
