"""Stage/promote this repair without overwriting the original migration ledger."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
from aws_sample_upload_probe import BASE,FOLDER
from recovery import ROOT

PROJECT="prj_4gnHN9F9bRu7vCsVQHVwrgJjXyq5"
MAIN="https://sentinel-document-intelligence.vercel.app"


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("action",choices=["candidate","promote"])
    action=parser.parse_args().action
    state=json.loads((BASE/"state.json").read_text());target=FOLDER/"vercel-production"
    cli=["npx.cmd","--yes","vercel@65.2.0"]
    def run(*args,cwd=None):
        r=subprocess.run([*cli,*args],cwd=cwd,capture_output=True,text=True,encoding="utf-8",timeout=300)
        if r.returncode:raise RuntimeError(r.stderr[-1800:])
        return r.stdout
    if action=="candidate":
        current=json.loads(run("inspect",MAIN,"--json"))
        assert current["name"]=="sentinel-document-intelligence"
        if (FOLDER/"production-before.json").exists() and not (FOLDER/"production-before-first.json").exists():
            shutil.copyfile(FOLDER/"production-before.json",FOLDER/"production-before-first.json")
        (FOLDER/"production-before.json").write_text(json.dumps(current,indent=2))
        env={**os.environ,"VITE_SENTINEL_MODE":"cloud","VITE_CLOUD_PROVIDER":"aws","VITE_API_BASE_URL":state["api_url"],
            "VITE_AWS_REGION":state["region"],"VITE_COGNITO_USER_POOL_ID":state["user_pool"],"VITE_COGNITO_CLIENT_ID":state["user_pool_client"],
            "VITE_ENABLE_GOOGLE_AUTH":"false","VITE_ENABLE_GITHUB_AUTH":"false"}
        subprocess.run(["npm.cmd","run","build"],cwd=ROOT/"frontend",env=env,check=True)
        target.mkdir(exist_ok=True)
        link=target/".vercel";link.mkdir(exist_ok=True)
        (link/"project.json").write_text(json.dumps({"projectId":PROJECT,"orgId":"team_NMXazl0BKRYhw51SmZ9t8b72"}))
        for output in (link/"output",target/"frontend/.vercel/output"):
            static=output/"static"
            if static.exists():
                assert not static.is_symlink() and target.resolve() in static.resolve().parents
                shutil.rmtree(static)
            shutil.copytree(ROOT/"frontend/dist",static)
            (output/"config.json").write_text('{"version":3}')
        deployed=json.loads(run("deploy","--prebuilt","--prod","--skip-domain","--yes","--json",cwd=target))
        url=deployed.get("url") or deployed.get("deployment",{}).get("url")
        assert url
        url=url.removeprefix("https://")
        (FOLDER/"candidate.json").write_text(json.dumps({"url":url,"metadata":deployed},indent=2))
        assert json.loads(run("inspect",MAIN,"--json"))["id"]==current["id"]
        print('Repair release staged; main domain unchanged')
    else:
        preview=json.loads((FOLDER/"preview-browser.json").read_text())
        assert preview["validRetrySucceeded"] and preview["sampleReused"] and not preview["consoleErrors"]
        checks=json.loads((FOLDER/"after.json").read_text())
        assert checks["sample_with_two_custom_cases"] and checks["invalid_csv_terminal_attempts"]==1 and checks["second_account_denied"]
        assert json.loads((FOLDER/"pre-change-backup.json").read_text())["Status"]=="Success"
        assert json.loads((FOLDER/"schema.json").read_text())["Status"]=="Success"
        before=json.loads((FOLDER/"production-before.json").read_text());candidate=json.loads((FOLDER/"candidate.json").read_text())
        candidate["url"]=candidate["url"].removeprefix("https://")
        current=json.loads(run("inspect",MAIN,"--json"))
        assert current["id"]==before["id"] or current["url"]==candidate["url"]
        assert json.loads((target/".vercel/project.json").read_text())["projectId"]==PROJECT
        if current["url"]!=candidate["url"]:
            run("promote",candidate["url"],"--yes",cwd=target)
        final=json.loads(run("inspect",MAIN,"--json"));assert final["url"]==candidate["url"]
        (FOLDER/"production-promoted.json").write_text(json.dumps(final,indent=2))
        print('Verified repair promoted to the existing main domain')


if __name__=="__main__":main()
