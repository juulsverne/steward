"""Per-request credential selection without changing process-wide environment."""
from botocore.credentials import CredentialProvider


def frozen_boto3_session(profile: str | None):
    import boto3
    import botocore.session

    if profile is not None:
        return boto3.Session(profile_name=profile)
    core = botocore.session.get_session()
    # ConfigValueStore treats None as an explicit override. The ordinary Session
    # instance variable does not. Leave credential providers (env, ECS, IMDS) intact.
    core.get_component("config_store").set_config_variable("profile", None)
    return boto3.Session(botocore_session=core)


class _ResolvedCredentials(CredentialProvider):
    """Serve one already-resolved (refreshable) credential object to another session."""

    METHOD = "steward-resolved"

    def __init__(self, credentials):
        super().__init__()
        self._credentials = credentials

    def load(self):
        return self._credentials


def region_session(profile: str | None, region: str):
    """A session bound to the service region whose credentials refresh in the profile's region.

    botocore's `aws login` provider refreshes its fifteen-minute access token through the
    sign-in endpoint of the session that resolved it. A session pinned to the Bedrock region
    asks a different sign-in endpoint and receives "authorization grant is invalid", so the
    credentials are resolved first by a session that keeps the profile's own configured
    region, then handed to the Bedrock-region session used for service clients.
    """
    import boto3
    import botocore.session

    credentials = _credential_session(profile).get_credentials()
    core = botocore.session.get_session()
    core.get_component("config_store").set_config_variable("profile", profile)
    core.set_config_variable("region", region)
    if credentials is not None:
        core.get_component("credential_provider").insert_before("env", _ResolvedCredentials(credentials))
    return boto3.Session(botocore_session=core)


def _credential_session(profile: str | None):
    """Resolve credentials where the profile's own configured region is authoritative."""
    import boto3
    import botocore.session

    if profile is None:
        return frozen_boto3_session(None)
    core = botocore.session.get_session()
    core.get_component("config_store").set_config_variable("profile", profile)
    configured = core.full_config.get("profiles", {}).get(profile, {}).get("region")
    if configured:
        # An AWS_DEFAULT_REGION in the environment must not redirect the login refresh.
        core.set_config_variable("region", configured)
    return boto3.Session(botocore_session=core)
