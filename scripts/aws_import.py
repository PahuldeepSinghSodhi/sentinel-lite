"""Copy the verified application backup to the shadow AWS deployment. No production cutover."""
from datetime import datetime,timezone
import argparse
import json
from pathlib import Path
import secrets
import time

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from aws_session import REGION,session
from recovery import load_backup,verify,unseal
from aws_commands import wait_command


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backup",type=Path,default=Path.home()/"SentinelRecovery/stage0-20261024")
    parser.add_argument("--key-file",type=Path,default=Path.home()/".sentinel-recovery-keys/stage0-20261024.key.dpapi")
    args=parser.parse_args()
    path=Path.home()/"SentinelRecovery/aws-migration/state.json"
    state=json.loads(path.read_text())
    aws=session()
    database=aws.client("rds").describe_db_instances(DBInstanceIdentifier=state["database"])["DBInstances"][0]
    if database["DBInstanceStatus"]!="available":
        raise RuntimeError("Database is still provisioning; import has not started")
    manager=aws.client("secretsmanager")
    master=json.loads(manager.get_secret_value(SecretId=state["bootstrap_secret"])["SecretString"])
    master["host"]=database["Endpoint"]["Address"]
    manager.put_secret_value(SecretId=state["bootstrap_secret"],SecretString=json.dumps(master))
    if "database_secret" not in state:
        app={**master,"username":"sentinel_app","password":secrets.token_urlsafe(36)}
        state["database_secret"]=manager.create_secret(Name="sentinel/database",SecretString=json.dumps(app),Tags=[{"Key":"Application","Value":"Sentinel"}])["ARN"]
        path.write_text(json.dumps(state,indent=2))
    backup=args.backup
    key_file=args.key_file
    verify(backup,key_file)
    directory,key,manifest=load_backup(backup,key_file)
    invites={i["email"]:i for i in manifest["tables"]["public.app_invites"]}
    users=[]
    identities=[]
    cognito=aws.client("cognito-idp")
    issuer=f"https://cognito-idp.{REGION}.amazonaws.com/{state['user_pool']}"
    for user in manifest["tables"]["auth.users"]:
        email=user["email"].strip().lower()
        verified=bool(user["email_confirmed_at"]) and not user["is_anonymous"]
        banned=bool(user["banned_until"] and datetime.fromisoformat(user["banned_until"])>datetime.now(timezone.utc))
        enabled=bool(invites.get(email,{}).get("enabled")) and verified and not banned and not user["deleted_at"]
        users.append({"id":user["id"],"email":email,"email_verified":verified,"disabled":not enabled,"created_at":user["created_at"]})
        if enabled:
            try:
                result=cognito.admin_get_user(UserPoolId=state["user_pool"],Username=email)
                attrs=result["UserAttributes"]
            except cognito.exceptions.UserNotFoundException:
                result=cognito.admin_create_user(UserPoolId=state["user_pool"],Username=email,MessageAction="SUPPRESS",
                    UserAttributes=[{"Name":"email","Value":email},{"Name":"email_verified","Value":"true"}])["User"]
                attrs=result["Attributes"]
            subject=next(a["Value"] for a in attrs if a["Name"]=="sub")
            identities.append({"issuer":issuer,"subject":subject,"app_user_id":user["id"]})
    tables={"app_users":users,"auth_identities":identities}
    # Preserve FK insertion order. No auth sessions, password hashes or Vault contents are read.
    for name in ("app_invites","cases","case_files","case_artifacts","jobs","scans","findings","investigations","questions"):
        tables[name]=manifest["tables"]["public."+name]
    tables["recovery_model_preferences"]=manifest["tables"]["public.model_settings"]
    storage=aws.client("s3")
    for obj in manifest["objects"]:
        content=unseal(key,(directory/obj["file"]).read_bytes(),obj["file"])
        storage.put_object(Bucket=state["bucket"],Key=obj["name"],Body=content,ServerSideEncryption="AES256",Metadata={"sha256":obj["sha256"]})
    payload=json.dumps({"tables":tables,"objects":[{k:o[k] for k in ("name","size","sha256")} for o in manifest["objects"]]},separators=(",",":")).encode()
    import_key=secrets.token_bytes(32)
    nonce=secrets.token_bytes(12)
    object_key="deployment/import-"+secrets.token_hex(8)+".enc"
    storage.put_object(Bucket=state["bucket"],Key=object_key,Body=nonce+AESGCM(import_key).encrypt(nonce,payload,b"sentinel-aws-import-v1"),ServerSideEncryption="AES256")
    if "migration_secret" not in state:
        state["migration_secret"]=manager.create_secret(Name="sentinel/bootstrap/migration-key",SecretString=import_key.hex(),Tags=[{"Key":"Application","Value":"Sentinel"}])["ARN"]
    else:
        manager.put_secret_value(SecretId=state["migration_secret"],SecretString=import_key.hex())
    # This command contains secret references, never secret values or private records.
    aws.client("iam").put_role_policy(RoleName="SentinelRuntime",PolicyName="SentinelTemporaryImport",PolicyDocument=json.dumps({
        "Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":"secretsmanager:GetSecretValue",
        "Resource":[state["bootstrap_secret"],state["migration_secret"]]}]}))
    # IAM grants are eventually consistent; give the new narrow grant time to propagate.
    time.sleep(10)
    command="docker run --rm --memory=512m -e AWS_REGION="+REGION
    for name,value in {"BOOTSTRAP_SECRET":state["bootstrap_secret"],"DATABASE_SECRET":state["database_secret"],
                       "MIGRATION_SECRET":state["migration_secret"],"BUCKET":state["bucket"],"IMPORT_KEY":object_key}.items():
        command+=" -e "+name+"="+value
    command+=" "+state["image"]+" python aws/initialize.py"
    result=aws.client("ssm").send_command(InstanceIds=[state["instance"]],DocumentName="AWS-RunShellScript",
        Parameters={"commands":["set -e",command],"executionTimeout":["600"]},Comment="Initialize and verify private Sentinel shadow database")
    state["import_command"]=result["Command"]["CommandId"]
    state["import_object"]=object_key
    path.write_text(json.dumps(state,indent=2))
    print(json.dumps({"import_command":state["import_command"],"objects_copied":len(manifest["objects"]),"invited_identities":len(identities)}),flush=True)
    try:
        wait_command(aws,state,state["import_command"],"import")
    finally:
        aws.client("iam").delete_role_policy(RoleName="SentinelRuntime",PolicyName="SentinelTemporaryImport")


if __name__=="__main__":
    main()
