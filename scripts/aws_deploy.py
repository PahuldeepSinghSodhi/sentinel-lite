"""Start only the AWS shadow API and warmed worker. No production frontend change."""
import base64
import argparse
import json
from pathlib import Path

from aws_session import REGION,session
from aws_commands import wait_command


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    flags=parser.add_mutually_exclusive_group()
    flags.add_argument("--read-only",action="store_true")
    flags.add_argument("--writable",action="store_true")
    parser.add_argument("--api-only",action="store_true")
    args=parser.parse_args()
    path=Path.home()/"SentinelRecovery/aws-migration/state.json"
    state=json.loads(path.read_text())
    if args.read_only:state["aws_read_only"]=True
    if args.writable:state["aws_read_only"]=False
    aws=session()
    aws.client("ecr").describe_images(repositoryName="sentinel",imageIds=[{"imageTag":state["source_revision"]}])
    result=aws.client("ssm").get_command_invocation(CommandId=state["import_command"],InstanceId=state["instance"])
    if result["Status"]!="Success":
        raise RuntimeError("The verified shadow import must succeed first")
    origins=["https://sentinel-document-intelligence.vercel.app"]
    if state.get("preview_url"):
        origins.append(state["preview_url"])
    origins=list(dict.fromkeys(origins+state.get("preview_origins",[])))
    env={"SENTINEL_MODE":"cloud","SENTINEL_CLOUD_PROVIDER":"aws","AWS_REGION":REGION,
         "SENTINEL_DATABASE_SECRET_ID":state["database_secret"],"SENTINEL_RDS_CA_FILE":"/app/aws/rds-ca.pem",
         "SENTINEL_STORAGE_BUCKET":state["bucket"],"SENTINEL_SECRET_PREFIX":"sentinel/providers",
         "COGNITO_USER_POOL_ID":state["user_pool"],"COGNITO_CLIENT_ID":state["user_pool_client"],
         "SENTINEL_FRONTEND_ORIGIN":origins[0],"SENTINEL_ALLOWED_ORIGINS":",".join(origins[1:])}
    if state.get("backup_bucket"):
        env.update(SENTINEL_BACKUP_BUCKET=state["backup_bucket"], SENTINEL_BACKUP_SECRET_ID=state["backup_secret"])
    env["SENTINEL_READ_ONLY"]="true" if state.get("aws_read_only",False) else "false"
    content="\n".join(f"{name}={value}" for name,value in env.items())+"\n"
    # The file contains references and public configuration only, no secret values.
    encoded=base64.b64encode(content.encode()).decode()
    commands=["set -euo pipefail","install -d -m 700 /opt/sentinel","install -d -m 755 /opt/sentinel/disk",
              f"printf %s {encoded} | base64 -d > /opt/sentinel/runtime.env","chmod 600 /opt/sentinel/runtime.env",
              "docker network inspect sentinel >/dev/null 2>&1 || docker network create sentinel"]
    commands.append("printf %s "+state["image"]+" > /opt/sentinel/current-image")
    registry=state["repository"].split("/")[0]
    commands += [f"trap 'docker logout {registry} >/dev/null 2>&1 || true' EXIT",
        f"aws ecr get-login-password --region {REGION} | docker login --username AWS --password-stdin {registry}",
        "docker pull "+state["image"],f"docker logout {registry}"]
    for name,memory,pool,extra in (("api","512m",3,f"-p {state['private_ip']}:8000:8000"),
                                   ("worker","1200m",2,"")):
        container_command="" if name=="api" else "python -m app.cloud.worker"
        unit=f"""[Unit]
Description=Sentinel {name}
After=docker.service network-online.target
Requires=docker.service
StartLimitIntervalSec=0

[Service]
Type=simple
Restart=on-failure
RestartSec=10
TimeoutStopSec=120
ExecStartPre=-/usr/bin/docker rm sentinel-{name}
ExecStart=/usr/bin/docker run --rm --name sentinel-{name} --init --read-only --cap-drop ALL --security-opt no-new-privileges --pids-limit 256 --tmpfs /tmp:rw,nosuid,nodev,size=256m --network sentinel {extra} --memory {memory} --memory-swap {memory} --cpus 1 --env-file /opt/sentinel/runtime.env -e SENTINEL_DB_POOL_SIZE={pool} --log-driver awslogs --log-opt awslogs-region={state['log_region']} --log-opt awslogs-group=/sentinel/application --log-opt awslogs-stream={name} --log-opt mode=non-blocking --log-opt max-buffer-size=4m {state['image']} {container_command}
ExecStop=/usr/bin/docker stop -t 100 sentinel-{name}

[Install]
WantedBy=multi-user.target
"""
        unit64=base64.b64encode(unit.encode()).decode()
        commands.append(f"printf %s {unit64} | base64 -d > /etc/systemd/system/sentinel-{name}.service")
    commands += ["systemctl daemon-reload","systemctl enable sentinel-api sentinel-worker",
                 "systemctl restart "+("sentinel-api" if args.api_only else "sentinel-api sentinel-worker"),
                 f"for attempt in $(seq 1 60); do curl --fail --silent --max-time 5 http://{state['private_ip']}:8000/health >/dev/null && break || true; sleep 2; done",
                 "systemctl is-active sentinel-api sentinel-worker", "docker stats --no-stream --format '{{.Name}} {{.MemUsage}} {{.CPUPerc}}'",
                 f"curl --fail --silent --max-time 10 http://{state['private_ip']}:8000/health", "free -m; df -h /"]
    response=aws.client("ssm").send_command(InstanceIds=[state["instance"]],DocumentName="AWS-RunShellScript",
        Parameters={"commands":commands,"executionTimeout":["300"]},Comment="Start private Sentinel shadow API and warmed worker")
    state["deploy_command"]=response["Command"]["CommandId"]
    path.write_text(json.dumps(state,indent=2))
    print(json.dumps({"deploy_command":state["deploy_command"],"image":state["image"]}),flush=True)
    wait_command(aws,state,state["deploy_command"],"deploy")


if __name__=="__main__":
    main()
