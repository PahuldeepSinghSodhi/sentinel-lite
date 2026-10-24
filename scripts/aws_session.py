"""Reuse the approved short-lived CLI session without printing or saving credentials."""
import json
import os
from pathlib import Path
import subprocess

REGION = "ap-southeast-2"
ACCOUNT = "315691290691"
PROFILE = "sentinel-migration"


def session():
    import boto3
    executable = os.getenv("SENTINEL_AWS_CLI") or str(
        Path.home() / "SentinelRecovery/tools/awscli/extracted/Amazon/AWSCLIV2/aws.exe")
    response = subprocess.run([executable, "configure", "export-credentials", "--profile", PROFILE,
                               "--format", "process"], capture_output=True, text=True, timeout=30)
    if response.returncode:
        raise RuntimeError("AWS project login is unavailable; renew the approved CLI session")
    temporary = json.loads(response.stdout)
    result = boto3.Session(aws_access_key_id=temporary["AccessKeyId"],
                           aws_secret_access_key=temporary["SecretAccessKey"],
                           aws_session_token=temporary["SessionToken"], region_name=REGION)
    if result.client("sts").get_caller_identity()["Account"] != ACCOUNT:
        raise RuntimeError("Refusing to operate outside the approved Fresh Deploy project")
    return result
