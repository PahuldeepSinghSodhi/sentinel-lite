"""Read-only final migration audit. Reports missing gates without exposing keys."""
from datetime import datetime,timezone
import json
from pathlib import Path
import requests
from aws_session import session
from aws_qualify import authenticated,request


def main():
    base=Path.home()/"SentinelRecovery/aws-migration"
    state=json.loads((base/"state.json").read_text());aws=session();checks={}
    checks["api_and_worker_ready"]=requests.get(state["api_url"]+"/health",timeout=15).status_code==200
    database=aws.client("rds").describe_db_instances(DBInstanceIdentifier=state["database"])["DBInstances"][0]
    checks["private_encrypted_database"]=database["StorageEncrypted"] and not database["PubliclyAccessible"] and database["DeletionProtection"]
    ec2=aws.client("ec2")
    instance=ec2.describe_instances(InstanceIds=[state["instance"]])["Reservations"][0]["Instances"][0]
    checks["metadata_requires_v2"]=instance["MetadataOptions"]["HttpTokens"]=="required"
    groups=ec2.describe_security_groups(GroupIds=[state["app_sg"],state["database_sg"]])["SecurityGroups"]
    checks["no_public_app_or_database_ingress"]=all(not r.get("IpRanges") and not r.get("Ipv6Ranges") for g in groups for r in g["IpPermissions"])
    for name in ("bucket","backup_bucket"):
        config=aws.client("s3").get_public_access_block(Bucket=state[name])["PublicAccessBlockConfiguration"]
        checks[name+"_private"]=all(config.values())
    pool=aws.client("cognito-idp").describe_user_pool(UserPoolId=state["user_pool"])["UserPool"]
    checks["signup_admin_only"]=pool["AdminCreateUserConfig"]["AllowAdminCreateUserOnly"]
    checks["email_otp_enabled"]="EMAIL_OTP" in pool["Policies"]["SignInPolicy"]["AllowedFirstAuthFactors"]
    app=aws.client("cognito-idp").describe_user_pool_client(UserPoolId=state["user_pool"],ClientId=state["user_pool_client"])["UserPoolClient"]
    checks["browser_client_has_no_secret"]="ClientSecret" not in app
    checks["ses_production_approved"]=aws.client("sesv2").get_account()["ProductionAccessEnabled"]
    iam=aws.client("iam")
    checks["temporary_permissions_removed"]=not any("Temporary" in p for p in iam.list_role_policies(RoleName="SentinelRuntime")["PolicyNames"])
    policy=iam.get_role_policy(RoleName="SentinelRuntime",PolicyName="SentinelResources")["PolicyDocument"]
    checks["no_standing_bootstrap_secret_access"]="/bootstrap/" not in json.dumps(policy)
    checks["schedules_enabled"]=all(aws.client("scheduler").get_schedule(Name=n)["State"]=="ENABLED" for n in state["schedules"])
    checks["alarm_email_confirmed"]=any(s["SubscriptionArn"].startswith("arn:") for s in aws.client("sns").list_subscriptions_by_topic(TopicArn=state["alarm_topic"])["Subscriptions"])
    plan=aws.client("freetier",region_name="us-east-1").get_account_plan_state()
    checks["active_free_plan"]=plan["accountPlanType"]=="FREE" and plan["accountPlanStatus"]=="ACTIVE"
    browser=json.loads((base/"browser-evidence.json").read_text())
    checks["real_chrome_continuity"]=browser["caseAndDraftPreserved"] and browser["nativeRefreshPreservedWorkspace"] and not browser["consoleErrors"]
    restored=json.loads((base/"restore-drill-verified-command.json").read_text())
    checks["isolated_restore_passed"]=restored["Status"]=="Success" and '"restore_verified": true' in restored["StandardOutputContent"]
    checks["off_account_backup_exists"]=Path(state["off_account_backup"]).joinpath("recovery-key.dpapi").is_file()
    checks["owner_key_reentered"]=request(authenticated("owner"),"GET","/me/model").json()["configured"]
    qualification=json.loads((base/"qualification.json").read_text())
    checks["hosted_ai_passed"]=qualification.get("owner_ai",{}).get("answer_saved",False)
    checks["hosted_investigation_passed"]=qualification.get("owner_investigation",{}).get("saved",False)
    if state.get("frontend_promoted"):
        workflow=json.loads((base/"production-workflow.json").read_text())
        checks["production_browser_passed"]=browser.get("testedUrl")=="https://sentinel-document-intelligence.vercel.app" and not browser.get("legacyBackendRequests")
        checks["production_ai_report_and_cors_passed"]=workflow["ai_answer_saved"] and workflow["production_download_cors_verified"]
        checks["legacy_compute_stopped"]=state.get("legacy_modal_stopped",False)
    result={"checked_at":datetime.now(timezone.utc).isoformat(),"checks":checks,
        "remaining_credits_usd":plan["accountPlanRemainingCredits"]["amount"],
        "preview_url":state["preview_url"],"production_cutover_complete":state.get("production_cutover_complete",False)}
    (base/"readiness.json").write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2))


if __name__=="__main__":main()
