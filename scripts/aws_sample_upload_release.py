"""Apply the additive sample/upload schema with a temporary bootstrap grant."""
import base64
import json
from pathlib import Path
import time

from aws_session import session
from aws_commands import wait_command


def main():
    base=Path.home()/"SentinelRecovery/aws-migration"
    state=json.loads((base/"state.json").read_text());aws=session()
    backup=json.loads((base/"sample-upload-fix/pre-change-backup.json").read_text())
    assert backup["Status"]=="Success"
    build=aws.client("ssm").get_command_invocation(CommandId=state["build_command"],InstanceId=state["instance"])
    assert build["Status"]=="Success","Wait for the verified image build"
    code="""import json,os
from pathlib import Path
import boto3,psycopg
secret=json.loads(boto3.client('secretsmanager',region_name=os.environ['AWS_REGION']).get_secret_value(SecretId=os.environ['BOOTSTRAP_SECRET'])['SecretString'])
with psycopg.connect(host=secret['host'],dbname='sentinel',user=secret['username'],password=secret['password'],sslmode='verify-full',sslrootcert='/app/aws/rds-ca.pem',connect_timeout=10) as c:
 c.execute("SET lock_timeout='5s'")
 c.execute("SET statement_timeout='30s'")
 c.execute(Path('/app/aws/schema.sql').read_text())
print('Additive sample/upload schema applied; existing cases preserved')
"""
    encoded=base64.b64encode(code.encode()).decode()
    iam=aws.client("iam")
    policy="SentinelTemporarySampleSchema"
    iam.put_role_policy(RoleName="SentinelRuntime",PolicyName=policy,PolicyDocument=json.dumps({"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":"secretsmanager:GetSecretValue","Resource":state["bootstrap_secret"]}]}))
    try:
        time.sleep(10)
        command=("set -euo pipefail\ncat /opt/sentinel/current-image\n"
            f"docker run --rm --read-only --memory=256m --tmpfs /tmp:rw,nosuid,nodev,size=32m --env-file /opt/sentinel/runtime.env -e BOOTSTRAP_SECRET={state['bootstrap_secret']} {state['image']} python -c \"import base64;exec(base64.b64decode('{encoded}'))\"")
        r=aws.client("ssm").send_command(InstanceIds=[state["instance"]],DocumentName="AWS-RunShellScript",Parameters={"commands":[command],"executionTimeout":["120"]},Comment="Additive sample and upload repair schema")
        result=wait_command(aws,state,r["Command"]["CommandId"],"sample-upload-schema",timeout=180)
        (base/"sample-upload-fix/schema.json").write_text(json.dumps(result,indent=2,default=str))
        print('Schema verified; temporary bootstrap access removed on completion')
    finally:
        iam.delete_role_policy(RoleName="SentinelRuntime",PolicyName=policy)


if __name__=="__main__":main()
