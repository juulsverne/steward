"""Per-request credential selection without changing process-wide environment."""


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
