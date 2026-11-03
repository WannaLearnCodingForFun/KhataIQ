"""M2.1: access-token and refresh-token rules."""

import time
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from khataiq.config import get_settings
from khataiq.models.enums import UserRole
from khataiq.security import (
    RefreshVerdict,
    StoredRefreshToken,
    TokenError,
    hash_refresh_token,
    issue_access_token,
    judge_refresh_token,
    new_refresh_token,
    verify_access_token,
)

NOW = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
WRONG_KEY = "wrong-key-that-is-at-least-32-bytes-long"


def test_round_trip():
    token, ttl = issue_access_token(7, 3, UserRole.OFFICER)
    claims = verify_access_token(token)
    assert (claims.user_id, claims.org_id, claims.role, ttl) == (7, 3, UserRole.OFFICER, 900)


def test_expired_token_is_rejected():
    token, _ = issue_access_token(7, 3, UserRole.OWNER, now=int(time.time()) - 3600)
    with pytest.raises(TokenError, match="expired"):
        verify_access_token(token)


def test_tampered_payload_is_rejected():
    token, _ = issue_access_token(7, 3, UserRole.OWNER)
    header, payload, signature = token.split(".")
    forged_payload = jwt.encode({"sub": "7", "org_id": 3, "role": "admin", "typ": "access",
                                 "exp": int(time.time()) + 60}, WRONG_KEY,
                                algorithm="HS256").split(".")[1]
    with pytest.raises(TokenError):
        verify_access_token(".".join([header, forged_payload, signature]))


def test_token_signed_with_another_secret_is_rejected():
    forged = jwt.encode({"sub": "1", "org_id": 1, "role": "admin", "typ": "access",
                         "exp": int(time.time()) + 60}, WRONG_KEY, algorithm="HS256")
    with pytest.raises(TokenError):
        verify_access_token(forged)


def test_alg_none_is_rejected():
    unsigned = jwt.encode({"sub": "1", "org_id": 1, "role": "admin", "typ": "access",
                           "exp": int(time.time()) + 60}, key=None, algorithm="none")
    with pytest.raises(TokenError):
        verify_access_token(unsigned)


def test_missing_claims_are_rejected():
    token = jwt.encode({"sub": "1", "exp": int(time.time()) + 60},
                       get_settings().jwt_secret.get_secret_value(), algorithm="HS256")
    with pytest.raises(TokenError):
        verify_access_token(token)


def test_refresh_tokens_are_random_and_hashed():
    a, b = new_refresh_token(), new_refresh_token()
    assert a != b and len(a) >= 43
    assert hash_refresh_token(a) == hash_refresh_token(a) != hash_refresh_token(b)


@pytest.mark.parametrize("stored, verdict", [
    (None, RefreshVerdict.UNKNOWN),
    (StoredRefreshToken(NOW + timedelta(days=1), None), RefreshVerdict.OK),
    (StoredRefreshToken(NOW - timedelta(seconds=1), None), RefreshVerdict.EXPIRED),
    (StoredRefreshToken(NOW + timedelta(days=1), NOW - timedelta(minutes=5)),
     RefreshVerdict.REUSED),
])
def test_refresh_verdicts(stored, verdict):
    assert judge_refresh_token(stored, NOW) == verdict


def test_reuse_wins_over_expiry():
    """A rotated token that has also expired is still reported as reuse, so the family dies."""
    stored = StoredRefreshToken(NOW - timedelta(days=1), NOW - timedelta(days=2))
    assert judge_refresh_token(stored, NOW) == RefreshVerdict.REUSED
