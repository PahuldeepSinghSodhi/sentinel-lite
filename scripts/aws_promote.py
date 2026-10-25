"""Promote the reviewed AWS frontend only after freeze, AI and recovery gates.

This changes Vercel public production configuration and aliases. It does not
resume writes or declare the migration complete; production smoke tests follow.
"""
import json
from pathlib import Path
import subprocess
import requests

from aws_qualify import authenticated,request

BASE=Path.home()/"SentinelRecovery/aws-migration"
MAIN="https://sentinel-document-intelligence.vercel.app"
PROJECT="prj_4gnHN9F9bRu7vCsVQHVwrgJjXyq5"


def main():
    path=BASE/"state.json";state=json.loads(path.read_text())
    target=BASE/"vercel-production-candidate"
    assert json.loads((target/".vercel/project.json").read_text())["projectId"]==PROJECT
    cli=["npx.cmd","--yes","vercel@65.2.0"]
    def run(*args,stdin=None):
        result=subprocess.run([*cli,*args,"--cwd",str(target)],input=stdin,capture_output=True,text=True,encoding="utf-8",timeout=300)
        if result.returncode:
            raise RuntimeError(result.stderr.encode("ascii","backslashreplace").decode()[-1500:])
        return result.stdout
    current=json.loads(run("inspect",MAIN,"--json"))
    if current["url"]==state["release_candidate_url"].removeprefix("https://"):
        print("Reviewed AWS frontend is already current; finish production checks")
        return
    assert current["url"]==state["production_before_aws"],"Production changed since candidate review"
    for url in (state["api_url"]+"/health","https://pahuldeepsinghsodhi--sentinel-cloud-api.us-east.modal.run/health"):
        response=requests.get(url,timeout=60);response.raise_for_status()
        assert response.json().get("writes_paused"),"Freeze both sides before promotion"
    assert state["both_job_queues_drained"] and state["source_business_state_unchanged"]
    assert Path(state["final_source_backup"]).is_dir()
    qualification=json.loads((BASE/"qualification.json").read_text())
    assert qualification["owner_ai"]["answer_saved"] and qualification["owner_investigation"]["saved"]
    assert request(authenticated("owner"),"GET","/me/model").json()["configured"]
    rollback=json.loads((BASE/"preview-rollback-evidence.json").read_text());assert rollback["verified"]
    backup=json.loads((BASE/"backup-verified-command.json").read_text())
    restored=json.loads((BASE/"restore-drill-verified-command.json").read_text())
    assert backup["Status"]==restored["Status"]=="Success"
    backup_data=json.loads(backup["StandardOutputContent"])
    restored_data=json.loads(restored["StandardOutputContent"])
    assert restored_data["restore_verified"] and backup_data["backup_prefix"]==restored_data["backup_prefix"]
    assert Path(state["off_account_backup"]).name==backup_data["backup_prefix"].strip("/").split("/")[-1]
    values={"VITE_SENTINEL_MODE":"cloud","VITE_CLOUD_PROVIDER":"aws","VITE_API_BASE_URL":state["api_url"],
        "VITE_AWS_REGION":state["region"],"VITE_COGNITO_USER_POOL_ID":state["user_pool"],
        "VITE_COGNITO_CLIENT_ID":state["user_pool_client"],"VITE_ENABLE_GOOGLE_AUTH":"false","VITE_ENABLE_GITHUB_AUTH":"false"}
    for name,value in values.items():
        run("env","add",name,"--environment","production","--force","--yes","--no-sensitive",stdin=value)
        print("Configured "+name,flush=True)
    run("promote",state["release_candidate_url"],"--yes")
    promoted=json.loads(run("inspect",MAIN,"--json"))
    assert promoted["url"]==state["release_candidate_url"].removeprefix("https://")
    assert promoted["readyState"]=="READY"
    state.update(frontend_promoted=True,production_deployment=promoted["url"],final_recovery_prefix=backup_data["backup_prefix"])
    path.write_text(json.dumps(state,indent=2))
    (BASE/"production-promotion.json").write_text(json.dumps(promoted,indent=2))
    print("Main domain now serves the reviewed AWS frontend; writes remain paused",flush=True)


if __name__=="__main__":main()
