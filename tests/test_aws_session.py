"""Credential sessions must refresh `aws login` tokens in the profile's own region."""
from pathlib import Path

import boto3
import pytest


@pytest.fixture
def isolated_aws_config(tmp_path: Path, monkeypatch):
    config = tmp_path / "config"
    config.write_text("[profile pc]\nregion = us-east-1\n", encoding="utf-8")
    monkeypatch.setenv("AWS_CONFIG_FILE", str(config))
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(tmp_path / "credentials"))
    for name in ("AWS_DEFAULT_REGION", "AWS_PROFILE", "AWS_DEFAULT_PROFILE"):
        monkeypatch.delenv(name, raising=False)
    return config


class FakeBoto3Session:
    """The offline guard blocks boto3.Session; observe the botocore session handed to it."""

    def __init__(self, *, botocore_session):
        self.core = botocore_session

    @property
    def region_name(self):
        return self.core.get_config_variable("region")

    def get_credentials(self):
        return self.core.get_credentials()


def test_region_session_binds_service_region_but_keeps_profile_resolved_credentials(monkeypatch, isolated_aws_config):
    from agent import aws_session

    sentinel = object()
    seen = []

    class CredentialSession:
        def get_credentials(self):
            return sentinel

    monkeypatch.setattr(boto3, "Session", FakeBoto3Session)
    monkeypatch.setattr(aws_session, "_credential_session",
                        lambda profile: seen.append(profile) or CredentialSession())
    session = aws_session.region_session("pc", "us-west-2")
    assert seen == ["pc"], "credentials resolve once through the profile-region session"
    assert session.region_name == "us-west-2"
    assert session.core.get_config_variable("profile") == "pc"
    assert session.get_credentials() is sentinel


def test_region_session_without_credentials_falls_back_to_ambient_resolution(monkeypatch, isolated_aws_config):
    from agent import aws_session

    class CredentialSession:
        def get_credentials(self):
            return None

    monkeypatch.setattr(boto3, "Session", FakeBoto3Session)
    monkeypatch.setattr(aws_session, "_credential_session", lambda profile: CredentialSession())
    session = aws_session.region_session(None, "us-west-2")
    assert session.region_name == "us-west-2"
    providers = [p.METHOD for p in session.core.get_component("credential_provider").providers]
    assert "steward-resolved" not in providers and "env" in providers


def test_credential_session_pins_the_profile_region_over_environment_defaults(monkeypatch, isolated_aws_config):
    from agent import aws_session

    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-west-2")
    monkeypatch.setattr(boto3, "Session", FakeBoto3Session)
    session = aws_session._credential_session("pc")
    assert session.region_name == "us-east-1"
    assert session.core.get_config_variable("profile") == "pc"
