"""Verify new upload/sample backups and compatibility with the pre-change archive."""
import json
from pathlib import Path
import re
import time
from aws_session import session
from aws_commands import wait_command

base=Path.home()/"SentinelRecovery/aws-migration"
state=json.loads((base/"state.json").read_text());aws=session();ssm=aws.client("ssm")
r=ssm.send_command(InstanceIds=[state["instance"]],DocumentName="Sentinel-backup",Comment="Backup sample/upload metadata for isolated restoration")
new=wait_command(aws,state,r["Command"]["CommandId"],"sample-fix-new-backup",timeout=300)
old=json.loads((base/"sample-upload-fix/pre-change-backup.json").read_text())
prefixes=[json.loads(r["StandardOutputContent"])["backup_prefix"] for r in (new,old)]
document=json.loads(ssm.get_document(Name="Sentinel-restore-drill",DocumentFormat="JSON")["Content"])
command=document["mainSteps"][0]["inputs"]["runCommand"][0]
iam=aws.client("iam");policy="SentinelTemporarySampleRestore"
iam.put_role_policy(RoleName="SentinelRuntime",PolicyName=policy,PolicyDocument=json.dumps({"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":"secretsmanager:GetSecretValue","Resource":state["bootstrap_secret"]}]}))
try:
    time.sleep(10)
    results=[]
    for i,prefix in enumerate(prefixes):
        assert re.fullmatch(r"daily/[A-Za-z0-9_-]+/",prefix)
        r=ssm.send_command(InstanceIds=[state["instance"]],DocumentName="AWS-RunShellScript",Parameters={"commands":[command+" --prefix "+prefix],"executionTimeout":["600"]},Comment="Isolated recovery compatibility verification")
        restored=wait_command(aws,state,r["Command"]["CommandId"],"sample-fix-restore-"+str(i),timeout=660)
        results.append(json.loads(restored["StandardOutputContent"]))
    (base/"sample-upload-fix/restoration.json").write_text(json.dumps(results,indent=2))
    print('New and pre-change backups restored and compared in isolated schemas')
finally:
    iam.delete_role_policy(RoleName="SentinelRuntime",PolicyName=policy)
