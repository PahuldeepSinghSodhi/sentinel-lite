"""Prepare an AWS frontend release in the existing Vercel project, without promotion.

Production aliases and environment variables remain unchanged. The separate AWS
preview is the functional review URL; this candidate is a staged release artifact.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from recovery import ROOT,protect_dir

PROJECT="prj_4gnHN9F9bRu7vCsVQHVwrgJjXyq5"
ORG="team_NMXazl0BKRYhw51SmZ9t8b72"
PRODUCTION="https://sentinel-document-intelligence.vercel.app"


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    base=Path.home()/"SentinelRecovery/aws-migration"
    path=base/"state.json";state=json.loads(path.read_text())
    cli=["npx.cmd","--yes","vercel@65.2.0"]
    current=json.loads(subprocess.run([*cli,"inspect",PRODUCTION,"--json"],capture_output=True,text=True,encoding="utf-8",check=True).stdout)
    if current["name"]!="sentinel-document-intelligence":
        raise RuntimeError("Unexpected production project")
    (base/"production-before-aws.json").write_text(json.dumps(current,indent=2))
    env={**os.environ,"VITE_SENTINEL_MODE":"cloud","VITE_CLOUD_PROVIDER":"aws","VITE_API_BASE_URL":state["api_url"],
        "VITE_AWS_REGION":state["region"],"VITE_COGNITO_USER_POOL_ID":state["user_pool"],"VITE_COGNITO_CLIENT_ID":state["user_pool_client"],
        "VITE_ENABLE_GOOGLE_AUTH":"false","VITE_ENABLE_GITHUB_AUTH":"false"}
    subprocess.run(["npm.cmd","run","build"],cwd=ROOT/"frontend",env=env,check=True)
    target=protect_dir(base/"vercel-production-candidate")
    link=target/".vercel";link.mkdir(exist_ok=True)
    (link/"project.json").write_text(json.dumps({"projectId":PROJECT,"orgId":ORG}))
    output=link/"output";static=output/"static"
    if static.exists():
        if static.is_symlink() or static.resolve()!=target.resolve()/".vercel/output/static":
            raise RuntimeError("Unexpected candidate output location")
        shutil.rmtree(static)
    shutil.copytree(ROOT/"frontend/dist",static)
    (output/"config.json").write_text('{"version":3}')
    # This existing project remembers frontend/ as its monorepo root. Both
    # layouts contain only the same public Build Output API artifact.
    project_output=target/"frontend/.vercel/output"
    project_output.mkdir(parents=True,exist_ok=True)
    if (project_output/"static").exists():
        duplicate=project_output/"static"
        if duplicate.is_symlink() or duplicate.resolve()!=target.resolve()/"frontend/.vercel/output/static":
            raise RuntimeError("Unexpected project output location")
        shutil.rmtree(duplicate)
    shutil.copytree(static,project_output/"static")
    (project_output/"config.json").write_text('{"version":3}')
    deployed=subprocess.run([*cli,"deploy","--prebuilt","--prod","--skip-domain","--yes","--json","--cwd",str(target)],
        capture_output=True,text=True,encoding="utf-8",timeout=300)
    if deployed.returncode:
        print(deployed.stderr[-1500:]);raise RuntimeError("Candidate deployment failed")
    data=json.loads(deployed.stdout)
    url=data.get("url") or data.get("deployment",{}).get("url")
    if not url:raise RuntimeError("Candidate metadata did not include its URL")
    after=json.loads(subprocess.run([*cli,"inspect",PRODUCTION,"--json"],capture_output=True,text=True,encoding="utf-8",check=True).stdout)
    if after["id"]!=current["id"]:
        raise RuntimeError("Production changed during candidate preparation; inspect before proceeding")
    state["production_before_aws"]=current["url"]
    state["release_candidate_url"]=url if url.startswith("https://") else "https://"+url
    (base/"release-candidate.json").write_text(json.dumps(data,indent=2))
    path.write_text(json.dumps(state,indent=2))
    print(json.dumps({"candidate_prepared":True,"production_unchanged":True}))


if __name__=="__main__":main()
