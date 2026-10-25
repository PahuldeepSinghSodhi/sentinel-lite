"""Isolated synthetic account for sample/upload regressions; secrets stay DPAPI encrypted."""
import argparse
import base64
import concurrent.futures
import json
from pathlib import Path
import secrets
import time
from uuid import uuid4

import requests
from aws_session import session
from aws_commands import wait_command
from recovery import dpapi

BASE = Path.home()/"SentinelRecovery/aws-migration"
FOLDER = BASE/"sample-upload-fix"


def remote(aws, state, code, label):
    encoded = base64.b64encode(code.encode()).decode()
    command = f"docker exec sentinel-api python -c \"import base64;exec(base64.b64decode('{encoded}'))\""
    result = aws.client("ssm").send_command(InstanceIds=[state["instance"]], DocumentName="AWS-RunShellScript",
        Parameters={"commands":[command]}, Comment="Synthetic sample/upload regression: "+label)
    return wait_command(aws,state,result["Command"]["CommandId"],label)["StandardOutputContent"]


def credentials():
    tokens=json.loads(dpapi((FOLDER/"qa-session.dpapi").read_bytes(),decrypt=True))
    import jwt
    if jwt.decode(tokens["IdToken"],options={"verify_signature":False})["exp"]<time.time()+120:
        import boto3
        from botocore import UNSIGNED
        from botocore.config import Config
        state=json.loads((BASE/"state.json").read_text())
        result=boto3.client("cognito-idp",region_name=state["region"],config=Config(signature_version=UNSIGNED)).initiate_auth(
            ClientId=state["user_pool_client"],AuthFlow="REFRESH_TOKEN_AUTH",AuthParameters={"REFRESH_TOKEN":tokens["RefreshToken"]})["AuthenticationResult"]
        tokens.update(result)
        (FOLDER/"qa-session.dpapi").write_bytes(dpapi(json.dumps(tokens).encode()))
    return tokens


def main():
    global FOLDER
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action",choices=["setup","before","after","cleanup"])
    parser.add_argument("--secondary",action="store_true")
    args=parser.parse_args();action=args.action
    if args.secondary:FOLDER=FOLDER/"secondary"
    FOLDER.mkdir(exist_ok=True)
    state=json.loads((BASE/"state.json").read_text())
    aws=session();cognito=aws.client("cognito-idp")
    ledger_path=FOLDER/"qa.json"
    if action=="setup":
        if ledger_path.exists():
            raise RuntimeError("Synthetic identity already recorded; reuse or clean it first")
        email=f"sentinel-fix-{uuid4().hex[:12]}@example.test"
        user=cognito.admin_create_user(UserPoolId=state["user_pool"],Username=email,MessageAction="SUPPRESS",
            UserAttributes=[{"Name":"email","Value":email},{"Name":"email_verified","Value":"true"}])["User"]
        subject=next(a["Value"] for a in user["Attributes"] if a["Name"]=="sub")
        owner=str(uuid4());password=secrets.token_urlsafe(32)+"aA1!"
        ledger={"email":email,"username":user["Username"],"subject":subject,"owner":owner,"cases":[]}
        ledger_path.write_text(json.dumps(ledger,indent=2))
        cognito.admin_set_user_password(UserPoolId=state["user_pool"],Username=user["Username"],Password=password,Permanent=True)
        tokens=cognito.initiate_auth(ClientId=state["user_pool_client"],AuthFlow="USER_AUTH",
            AuthParameters={"USERNAME":email,"PREFERRED_CHALLENGE":"PASSWORD","PASSWORD":password})["AuthenticationResult"]
        (FOLDER/"qa-session.dpapi").write_bytes(dpapi(json.dumps(tokens).encode()))
        issuer=f"https://cognito-idp.{state['region']}.amazonaws.com/{state['user_pool']}"
        code=f"""from app.cloud import db
with db.connect() as c:
 c.execute('INSERT INTO app_users(id,email,email_verified) VALUES (%s,%s,true)',({owner!r},{email!r}))
 c.execute('INSERT INTO auth_identities(issuer,subject,app_user_id) VALUES (%s,%s,%s)',({issuer!r},{subject!r},{owner!r}))
 c.execute('INSERT INTO app_invites(email) VALUES (%s)',({email!r},))
print('Synthetic invited account created')
"""
        print(remote(aws,state,code,"sample-fix-qa-setup").strip());return
    ledger=json.loads(ledger_path.read_text())
    if action=="cleanup":
        owner=ledger["owner"];email=ledger["email"]
        code=f"""from app.cloud import db,store
from app.cloud.auth import user_context
with user_context({{'id':{owner!r},'email':{email!r},'role':'reviewer'}}):
 for case in store.list_cases(): store.delete_case(str(case['id']))
with db.connect() as c:
 c.execute('UPDATE app_users SET disabled=true WHERE id=%s',({owner!r},))
 c.execute('UPDATE app_invites SET enabled=false WHERE email=%s',({email!r},))
print('Only synthetic test cases removed; QA identity disabled')
"""
        print(remote(aws,state,code,"sample-fix-qa-cleanup").strip())
        cognito.admin_disable_user(UserPoolId=state["user_pool"],Username=ledger["username"])
        (FOLDER/"qa-session.dpapi").unlink(missing_ok=True);return
    s=requests.Session();s.headers["Authorization"]="Bearer "+credentials()["IdToken"]
    def req(method,path,**kwargs):
        return s.request(method,state["api_url"]+path,timeout=40,**kwargs)
    if action=="before":
        outcomes=[]
        for _ in range(2):
            result=req("POST","/cases/demo")
            body=result.json();outcomes.append({"status":result.status_code,"detail":body.get("detail"),"ready":body.get("ready")})
            time.sleep(3)
        print(json.dumps({"sample_attempts":outcomes}))
        (FOLDER/"before.json").write_text(json.dumps(outcomes,indent=2))
    else:
        def checked(method,path,**kwargs):
            response=req(method,path,**kwargs);response.raise_for_status();return response.json()
        def wait_job(job):
            deadline=time.monotonic()+180
            while time.monotonic()<deadline:
                current=checked("GET","/jobs/"+job["job_id"])
                if current["status"]=="failed":return current
                if current["status"]=="completed":return current
                time.sleep(1)
            raise RuntimeError("Synthetic operation did not finish")
        cases=[case for case in checked("GET","/cases") if not checked("GET","/cases/"+case["id"]).get("is_sample")]
        assert len(cases)==2,"Reproduction should leave two custom cases"
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            samples=list(pool.map(lambda _:checked("POST","/cases/demo"),range(3)))
        assert len({c["id"] for c in samples})==1
        case_id=samples[0]["id"]
        deadline=time.monotonic()+120
        while time.monotonic()<deadline:
            case=checked("GET","/cases/"+case_id)
            if case["ready"]:break
            if case["job"]["status"]=="failed":raise RuntimeError(case["job"]["error"])
            time.sleep(1.5)
        assert case["ready"] and set(case["files"])=={"transactions","rate_card","contract"}
        assert checked("GET","/me/model")["configured"] is False
        scan=wait_job(checked("POST",f"/cases/{case_id}/scans"));assert scan["status"]=="completed"
        case=checked("GET","/cases/"+case_id)
        assert case["scans"][-1]["transactions_analyzed"]==12
        finding=case["scans"][-1]["findings"][0]
        checked("PATCH",f"/cases/{case_id}/findings/{finding['id']}",json={"decision":"investigate","note":"Synthetic private sample continuity check"})
        reopened=checked("POST","/cases/demo")
        assert reopened["id"]==case_id and reopened["scans"][-1]["findings"][0]["decision"]=="investigate"
        report=checked("GET",f"/cases/{case_id}/report")
        if report.get("job_id"):assert wait_job(report)["status"]=="completed"
        report=checked("GET",f"/cases/{case_id}/report")
        pdf=requests.get(report["url"],timeout=30);pdf.raise_for_status();assert pdf.content.startswith(b"%PDF")
        custom=next(c for c in cases if c["name"]=="AWS synthetic invalid CSV regression")
        def upload(kind,name,data):
            ticket=checked("POST",f"/cases/{custom['id']}/uploads/{kind}",json={"filename":name,"size":len(data)})
            r=requests.post(ticket["url"],data=ticket["fields"],files={"file":(name,data)},timeout=30);r.raise_for_status()
            return wait_job(checked("POST",f"/cases/{custom['id']}/uploads/{ticket['upload_id']}/confirm"))
        invalid=upload("transactions","random.csv",b"random_column,other_column\none,two\n")
        assert invalid["status"]=="failed" and invalid["attempts"]==1 and invalid["error_code"]=="upload_invalid"
        assert "Missing required columns" in invalid["error"]
        root=Path(__file__).resolve().parents[1]/"backend/data"
        for kind,name in (("transactions","sample_transactions.csv"),("rate_card","rate_card.csv"),("contract","sample_docs/service_agreement.txt")):
            assert upload(kind,Path(name).name,(root/name).read_bytes())["status"]=="completed"
        assert upload("transactions","replacement.csv",b"wrong\nvalue\n")["status"]=="failed"
        assert checked("GET",f"/cases/{custom['id']}")["files"]["transactions"]["filename"]=="sample_transactions.csv"
        reserved=checked("POST",f"/cases/{custom['id']}/uploads/transactions",json={"filename":"cancel.csv","size":3})
        cancelled=req("DELETE",f"/cases/{custom['id']}/uploads/{reserved['upload_id']}");assert cancelled.status_code==204
        assert upload("transactions","retry.csv",(root/"sample_transactions.csv").read_bytes())["status"]=="completed"
        second=json.loads(dpapi((BASE/"sample-upload-fix/secondary/qa-session.dpapi").read_bytes(),decrypt=True))
        denied=requests.get(state["api_url"]+"/cases/"+case_id,headers={"Authorization":"Bearer "+second["IdToken"]},timeout=30)
        assert denied.status_code==404
        locked=req("POST",f"/cases/{case_id}/uploads/transactions",json={"filename":"replace.csv","size":3});assert locked.status_code==400
        result={"sample_with_two_custom_cases":True,"concurrent_sample_requests_same_case":True,"three_sample_files":True,"sample_scan_rows":12,
            "sample_findings":len(case["scans"][-1]["findings"]),"sample_report_without_ai_key":True,"sample_reopen_preserves_decision":True,
            "invalid_csv_terminal_attempts":invalid["attempts"],"validation_reason_visible":True,"valid_csv_and_txt":True,
            "failed_replacement_preserves_file":True,"cancel_and_retry_passed":True,"second_account_denied":True,"sample_sources_locked":True,
            "sample_case":case_id,"custom_case":custom["id"],"report_bytes":len(pdf.content)}
        (FOLDER/"after.json").write_text(json.dumps(result,indent=2));print(json.dumps(result))


if __name__=="__main__":main()
