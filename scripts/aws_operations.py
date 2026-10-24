"""Provision bounded scheduled recovery and monitoring for the dedicated AWS stack."""
import argparse
import json
from pathlib import Path
import secrets
import time

from botocore.exceptions import ClientError
from aws_session import ACCOUNT, REGION, session
from aws_commands import wait_command

BASE = Path.home()/"SentinelRecovery/aws-migration"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", choices=["backup", "monitor", "restore-drill"])
    args = parser.parse_args()
    path = BASE/"state.json"
    state = json.loads(path.read_text())
    aws = session()
    def save(name, value):
        state[name] = value
        path.write_text(json.dumps(state, indent=2))
    bucket = f"sentinel-recovery-{ACCOUNT}-{REGION}"
    s3 = aws.client("s3")
    if not state.get("backup_bucket"):
        try:
            s3.create_bucket(Bucket=bucket, CreateBucketConfiguration={"LocationConstraint": REGION})
        except ClientError as exc:
            if exc.response["Error"]["Code"] != "BucketAlreadyOwnedByYou":
                raise
        save("backup_bucket", bucket)
    s3.put_public_access_block(Bucket=bucket, PublicAccessBlockConfiguration={
        "BlockPublicAcls": True,"IgnorePublicAcls": True,"BlockPublicPolicy": True,"RestrictPublicBuckets": True})
    s3.put_bucket_ownership_controls(Bucket=bucket, OwnershipControls={"Rules":[{"ObjectOwnership":"BucketOwnerEnforced"}]})
    s3.put_bucket_encryption(Bucket=bucket, ServerSideEncryptionConfiguration={"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]})
    s3.put_bucket_lifecycle_configuration(Bucket=bucket, LifecycleConfiguration={"Rules":[{
        "ID":"Retain-seven-complete-days","Status":"Enabled","Filter":{"Prefix":"daily/"},"Expiration":{"Days":8},
        "AbortIncompleteMultipartUpload":{"DaysAfterInitiation":1}}]})
    s3.put_bucket_policy(Bucket=bucket, Policy=json.dumps({"Version":"2012-10-17","Statement":[{
        "Effect":"Deny","Principal":"*","Action":"s3:*","Resource":[f"arn:aws:s3:::{bucket}",f"arn:aws:s3:::{bucket}/*"],
        "Condition":{"Bool":{"aws:SecureTransport":"false"}}}]}))
    s3.put_bucket_lifecycle_configuration(Bucket=state["bucket"], LifecycleConfiguration={"Rules":[{
        "ID":"Expire-abandoned-staging","Status":"Enabled","Filter":{"Prefix":"staging/"},"Expiration":{"Days":1},
        "AbortIncompleteMultipartUpload":{"DaysAfterInitiation":1}}]})
    if not state.get("backup_secret"):
        save("backup_secret", aws.client("secretsmanager").create_secret(Name="sentinel/operations/backup-key",
            SecretString=secrets.token_bytes(32).hex(), Tags=[{"Key":"Application","Value":"Sentinel"}])["ARN"])
    iam = aws.client("iam")
    iam.put_role_policy(RoleName="SentinelRuntime", PolicyName="SentinelRecovery", PolicyDocument=json.dumps({
        "Version":"2012-10-17","Statement":[
            {"Effect":"Allow","Action":["s3:ListBucket"],"Resource":f"arn:aws:s3:::{bucket}","Condition":{"StringLike":{"s3:prefix":"daily/*"}}},
            {"Effect":"Allow","Action":["s3:GetObject","s3:PutObject"],"Resource":f"arn:aws:s3:::{bucket}/daily/*"},
            {"Effect":"Allow","Action":"secretsmanager:GetSecretValue","Resource":state["backup_secret"]}]}))
    iam.put_role_policy(RoleName="SentinelRuntime",PolicyName="SentinelCreditStatus",PolicyDocument=json.dumps({
        "Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":"freetier:GetAccountPlanState","Resource":"*"}]}))
    sns = aws.client("sns")
    topic = sns.create_topic(Name="sentinel-operations", Tags=[{"Key":"Application","Value":"Sentinel"}])["TopicArn"]
    save("alarm_topic", topic)
    subs = sns.list_subscriptions_by_topic(TopicArn=topic)["Subscriptions"]
    if not any(s.get("Endpoint")==state["email_sender"] for s in subs):
        sns.subscribe(TopicArn=topic, Protocol="email", Endpoint=state["email_sender"])
    cw = aws.client("cloudwatch")
    for name, threshold, comparison, missing in (
        ("WorkerAgeSeconds",150,"GreaterThanThreshold","breaching"),
        ("BackupAgeSeconds",93600,"GreaterThanThreshold","breaching"),
        ("OldestPendingSeconds",600,"GreaterThanThreshold","notBreaching"),
        ("AvailableMemoryMiB",200,"LessThanThreshold","notBreaching"),
        ("DiskFreePercent",20,"LessThanThreshold","notBreaching"),
        ("FailedJobs24h",0,"GreaterThanThreshold","notBreaching"),
        ("OperationFailure",0,"GreaterThanThreshold","notBreaching")):
        cw.put_metric_alarm(AlarmName="Sentinel-"+name, Namespace="Sentinel", MetricName=name,
            Statistic="Maximum" if comparison=="GreaterThanThreshold" else "Minimum", Period=300,
            EvaluationPeriods=2 if name=="WorkerAgeSeconds" else 1, Threshold=threshold, ComparisonOperator=comparison,
            TreatMissingData=missing, AlarmActions=[topic], OKActions=[topic])
    for name,threshold in (("RemainingCreditsUSD",20),("FreePlanActive",1),("APIReady",1)):
        cw.put_metric_alarm(AlarmName="Sentinel-"+name,Namespace="Sentinel",MetricName=name,Statistic="Minimum",Period=300,
            EvaluationPeriods=1,Threshold=threshold,ComparisonOperator="LessThanThreshold",TreatMissingData="breaching",AlarmActions=[topic])
    cw.put_metric_alarm(AlarmName="Sentinel-EC2-status", Namespace="AWS/EC2", MetricName="StatusCheckFailed",
        Dimensions=[{"Name":"InstanceId","Value":state["instance"]}],Statistic="Maximum",Period=300,
        EvaluationPeriods=2,Threshold=0,ComparisonOperator="GreaterThanThreshold",TreatMissingData="breaching",AlarmActions=[topic])
    cw.put_metric_alarm(AlarmName="Sentinel-CPU-credit-reserve",Namespace="AWS/EC2",MetricName="CPUCreditBalance",
        Dimensions=[{"Name":"InstanceId","Value":state["instance"]}],Statistic="Minimum",Period=300,
        EvaluationPeriods=2,Threshold=30,ComparisonOperator="LessThanThreshold",TreatMissingData="notBreaching",AlarmActions=[topic])
    ssm = aws.client("ssm")
    documents = {}
    for action in ("backup","monitor","restore-drill"):
        name = "Sentinel-"+action
        bootstrap = " -e BOOTSTRAP_SECRET="+state["bootstrap_secret"] if action=="restore-drill" else ""
        command = ("set -euo pipefail\nIMAGE=$(cat /opt/sentinel/current-image)\n"
                   "docker run --rm --init --read-only --cap-drop ALL --security-opt no-new-privileges "
                   "--memory 256m --memory-swap 256m --cpus 0.5 --tmpfs /tmp:rw,nosuid,nodev,size=64m "
                   "--env-file /opt/sentinel/runtime.env -e SENTINEL_DB_POOL_SIZE=1 "
                   "--mount type=bind,src=/proc/meminfo,dst=/host-meminfo,readonly "
                   "--mount type=bind,src=/opt/sentinel/disk,dst=/host-root,readonly "
                   +bootstrap+' "$IMAGE" python -m aws.operations '+action)
        document = json.dumps({"schemaVersion":"2.2","description":"Fixed Sentinel "+action+"; no arbitrary command parameters",
            "mainSteps":[{"action":"aws:runShellScript","name":"sentinelOperation","inputs":{"runCommand":[command],"timeoutSeconds":"900"}}]})
        try:
            ssm.create_document(Name=name,Content=document,DocumentType="Command",DocumentFormat="JSON",Tags=[{"Key":"Application","Value":"Sentinel"}])
        except ssm.exceptions.DocumentAlreadyExists:
            try:
                result=ssm.update_document(Name=name,Content=document,DocumentVersion="$LATEST",DocumentFormat="JSON")
                ssm.update_document_default_version(Name=name,DocumentVersion=result["DocumentDescription"]["DocumentVersion"])
            except ssm.exceptions.DuplicateDocumentContent:
                pass
        documents[action]=name
    # The scheduler can invoke only these documents on this single instance.
    trust={"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"scheduler.amazonaws.com"},"Action":"sts:AssumeRole",
        "Condition":{"StringEquals":{"aws:SourceAccount":ACCOUNT},"ArnLike":{"aws:SourceArn":f"arn:aws:scheduler:{REGION}:{ACCOUNT}:schedule-group/default"}}}]}
    try:
        role=iam.create_role(RoleName="SentinelScheduler",Path="/sentinel/",AssumeRolePolicyDocument=json.dumps(trust))["Role"]
    except iam.exceptions.EntityAlreadyExistsException:
        role=iam.get_role(RoleName="SentinelScheduler")["Role"]
        iam.update_assume_role_policy(RoleName="SentinelScheduler",PolicyDocument=json.dumps(trust))
    iam.put_role_policy(RoleName="SentinelScheduler",PolicyName="FixedSentinelOperations",PolicyDocument=json.dumps({
        "Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":"ssm:SendCommand","Resource":[
            f"arn:aws:ec2:{REGION}:{ACCOUNT}:instance/{state['instance']}",
            *[f"arn:aws:ssm:{REGION}:{ACCOUNT}:document/{documents[a]}" for a in ("backup","monitor")]]}]}))
    scheduler=aws.client("scheduler")
    for action, expression in (("monitor","rate(5 minutes)"),("backup","cron(15 18 * * ? *)")):
        settings={"Name":"Sentinel-"+action,"ScheduleExpression":expression,"ScheduleExpressionTimezone":"UTC",
            "FlexibleTimeWindow":{"Mode":"OFF"},"State":"ENABLED","Target":{
                "Arn":"arn:aws:scheduler:::aws-sdk:ssm:sendCommand","RoleArn":role["Arn"],
                "Input":json.dumps({"DocumentName":documents[action],"InstanceIds":[state["instance"]],
                    "CloudWatchOutputConfig":{"CloudWatchLogGroupName":"/sentinel/application","CloudWatchOutputEnabled":True}}),
                "RetryPolicy":{"MaximumEventAgeInSeconds":900,"MaximumRetryAttempts":2}}}
        try:
            scheduler.create_schedule(**settings)
        except scheduler.exceptions.ConflictException:
            scheduler.update_schedule(**settings)
    save("schedules",["Sentinel-monitor","Sentinel-backup"])
    if args.run:
        if args.run=="restore-drill":
            iam.put_role_policy(RoleName="SentinelRuntime",PolicyName="SentinelTemporaryRestore",PolicyDocument=json.dumps({
                "Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":"secretsmanager:GetSecretValue","Resource":state["bootstrap_secret"]}]}))
            time.sleep(10)
        result=ssm.send_command(InstanceIds=[state["instance"]],DocumentName=documents[args.run],
            CloudWatchOutputConfig={"CloudWatchLogGroupName":"/sentinel/application","CloudWatchOutputEnabled":True})
        save("operations_command",result["Command"]["CommandId"])
        print(json.dumps({"operation":args.run,"command":state["operations_command"]}))
        try:
            wait_command(aws,state,state["operations_command"],args.run)
        finally:
            if args.run=="restore-drill":
                iam.delete_role_policy(RoleName="SentinelRuntime",PolicyName="SentinelTemporaryRestore")
    print(json.dumps({"backup_bucket":bucket,"scheduled":state["schedules"],"alarms":12}))


if __name__ == "__main__":
    main()
