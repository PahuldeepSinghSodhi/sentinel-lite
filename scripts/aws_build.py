"""Build an immutable CPU-only image on the isolated EC2 host through Systems Manager."""
import hashlib
import json
from pathlib import Path
import tarfile
import time

from aws_session import ACCOUNT, REGION, session
from recovery import ROOT
from aws_commands import wait_command


def main():
    state_path = Path.home() / "SentinelRecovery/aws-migration/state.json"
    state = json.loads(state_path.read_text())
    aws = session()
    if state.get("build_command"):
        previous=aws.client("ssm").get_command_invocation(CommandId=state["build_command"],InstanceId=state["instance"])
        if previous["Status"] in {"Pending","InProgress","Delayed"}:
            raise RuntimeError("A build is already running; wait before starting another on the small server")
    backend = ROOT / "backend"
    files = [p for folder in (backend / "app", backend / "aws") for p in folder.rglob("*")
             if p.is_file() and "__pycache__" not in p.parts and not p.is_symlink()]
    files += [backend / "data" / name for name in ("sample_transactions.csv","rate_card.csv","sample_docs/service_agreement.txt")]
    hasher = hashlib.sha256()
    for path in sorted(files):
        assert not path.name.startswith(".env") and path.suffix != ".pyc"
        hasher.update(str(path.relative_to(backend)).encode())
        hasher.update(path.read_bytes())
    revision = hasher.hexdigest()[:16]
    image = state["repository"] + ":" + revision
    try:
        aws.client("ecr").describe_images(repositoryName="sentinel",imageIds=[{"imageTag":revision}])
        state.update(image=image,source_revision=revision)
        state_path.write_text(json.dumps(state,indent=2))
        print(json.dumps({"image":image,"immutable_image_already_built":True}),flush=True)
        return
    except aws.client("ecr").exceptions.ImageNotFoundException:
        pass
    archive = state_path.parent / f"source-{revision}.tar.gz"
    with tarfile.open(archive,"w:gz") as tar:
        for path in files:
            tar.add(path,arcname=path.relative_to(backend).as_posix(),recursive=False)
    key = f"deployment/source-{revision}.tar.gz"
    aws.client("s3").upload_file(str(archive),state["bucket"],key,ExtraArgs={"ServerSideEncryption":"AES256"})
    aws.client("iam").put_role_policy(RoleName="SentinelRuntime",PolicyName="SentinelTemporaryBuild",PolicyDocument=json.dumps({
        "Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":["ecr:InitiateLayerUpload","ecr:UploadLayerPart","ecr:CompleteLayerUpload","ecr:PutImage"],
        "Resource":f"arn:aws:ecr:{REGION}:{ACCOUNT}:repository/sentinel"}]}))
    time.sleep(10)  # wait for the temporary push grant before minting the ECR login
    registry=state['repository'].split('/')[0]
    commands = ["set -euo pipefail", f"trap 'docker logout {registry} >/dev/null 2>&1 || true' EXIT", "command -v aws >/dev/null || dnf install -y awscli-2",
                f"install -d -m 700 /opt/sentinel/build/{revision}",
                f"aws s3 cp s3://{state['bucket']}/{key} /opt/sentinel/build/{revision}/source.tar.gz --region {REGION} --only-show-errors",
                f"tar -xzf /opt/sentinel/build/{revision}/source.tar.gz -C /opt/sentinel/build/{revision}",
                f"cd /opt/sentinel/build/{revision}",
                f"docker build --memory=1500m -f aws/Dockerfile -t {image} . > /opt/sentinel/build-{revision}.log 2>&1",
                f"aws ecr get-login-password --region {REGION} | docker login --username AWS --password-stdin {state['repository'].split('/')[0]}",
                f"docker push {image} >> /opt/sentinel/build-{revision}.log 2>&1",
                f"docker logout {state['repository'].split('/')[0]}",
                f"docker image inspect {image} --format '{{{{.Id}}}}'", "free -m; df -h /"]
    result = aws.client("ssm").send_command(InstanceIds=[state["instance"]],DocumentName="AWS-RunShellScript",
        Parameters={"commands":commands,"executionTimeout":["3600"]},Comment="Build pinned CPU-only Sentinel migration image")
    state.update(build_command=result["Command"]["CommandId"],image=image,source_revision=revision)
    state_path.write_text(json.dumps(state,indent=2))
    print(json.dumps({"build_command":state["build_command"],"image":image,"source_files":len(files)}),flush=True)
    try:
        wait_command(aws,state,state["build_command"],"build",timeout=3660)
    finally:
        aws.client("iam").delete_role_policy(RoleName="SentinelRuntime",PolicyName="SentinelTemporaryBuild")


if __name__ == "__main__":
    main()
