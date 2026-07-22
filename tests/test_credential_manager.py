import pytest

from repo_guardian.gateway.credential_manager import CredentialError, ScopedTokenFactory


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def test_token_is_single_use():
    factory = ScopedTokenFactory()
    token = factory.get_scoped_token("tier2", "post_comment", "run-1")
    factory.validate_token(token, "post_comment")
    with pytest.raises(CredentialError, match="already been used"):
        factory.validate_token(token, "post_comment")


def test_token_expires_after_ttl():
    clock = Clock()
    factory = ScopedTokenFactory(ttl_seconds=5, clock=clock)
    token = factory.get_scoped_token("tier1", "get_pr", "run-1")
    clock.now += 5
    with pytest.raises(CredentialError, match="expired"):
        factory.validate_token(token, "get_pr")


def test_token_is_scoped_to_one_tool():
    factory = ScopedTokenFactory()
    token = factory.get_scoped_token("tier2", "post_comment", "run-1")
    with pytest.raises(CredentialError, match="not scoped"):
        factory.validate_token(token, "add_label")
    factory.validate_token(token, "post_comment")
