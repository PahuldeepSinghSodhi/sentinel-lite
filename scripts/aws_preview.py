"""Build the AWS frontend locally and publish only to the separate preview project."""
import json
import os
from pathlib import Path
import shutil
import subprocess

from recovery import ROOT,protect_dir


def main():
    state_path=Path.home()/"SentinelRecovery/aws-migration/state.json"
    state=json.loads(state_path.read_text())
    env={**os.environ,"VITE_SENTINEL_MODE":"cloud","VITE_CLOUD_PROVIDER":"aws","VITE_API_BASE_URL":state["api_url"],
         "VITE_AWS_REGION":state["region"],"VITE_COGNITO_USER_POOL_ID":state["user_pool"],"VITE_COGNITO_CLIENT_ID":state["user_pool_client"],
         "VITE_ENABLE_GOOGLE_AUTH":"false","VITE_ENABLE_GITHUB_AUTH":"false"}
    subprocess.run(["npm.cmd","run","build"],cwd=ROOT/"frontend",env=env,check=True)
    target=protect_dir(state_path.parent/"vercel-preview")
    output=target/".vercel/output"
    static=output/"static"
    if static.exists():
        if static.is_symlink() or static.resolve() != target.resolve()/".vercel/output/static":
            raise RuntimeError("Unexpected preview output location")
        shutil.rmtree(static)
    static.mkdir(parents=True,exist_ok=True)
    # Copy only the public build output, never environment files, tokens, or source data.
    shutil.copytree(ROOT/"frontend/dist",static,dirs_exist_ok=True)
    (output/"config.json").write_text(json.dumps({"version":3}))
    cli=["npx.cmd","--yes","vercel@65.2.0"]
    subprocess.run([*cli,"link","--yes","--project","sentinel-aws-preview","--cwd",str(target)],check=True)
    linked=json.loads((target/".vercel/project.json").read_text())
    if linked["projectId"]!="prj_f3iqVs78zKmPV1LVLjC5o8zD8AvP":
        raise RuntimeError("Refusing to deploy outside the dedicated preview project")
    deployment=subprocess.run([*cli,"deploy","--prebuilt","--prod","--yes","--json","--cwd",str(target)],capture_output=True,text=True,timeout=300)
    if deployment.returncode:
        print(deployment.stderr[-2000:])
        raise RuntimeError("Preview deployment failed")
    data=json.loads(deployment.stdout)
    # CLI JSON shape is kept in private evidence for troubleshooting SDK changes.
    (state_path.parent/"preview-deployment.json").write_text(json.dumps(data,indent=2))
    url=data.get("url") or data.get("deployment",{}).get("url")
    inspected=subprocess.run([*cli,"inspect",url,"--json"],capture_output=True,text=True,check=True)
    metadata=json.loads(inspected.stdout)
    aliases=metadata.get("aliases",[])
    chosen=next((a for a in aliases if a=="sentinel-aws-preview.vercel.app"),url)
    if not chosen:
        raise RuntimeError("Preview deployed; inspect deployment metadata for its URL")
    old=state.get("preview_url")
    state["preview_url"]=chosen if chosen.startswith("https://") else "https://"+chosen
    state["preview_deployment_url"]=url if str(url).startswith("https://") else "https://"+str(url)
    state["preview_origins"]=list(dict.fromkeys([*state.get("preview_origins",[]),*[o for o in (old,state["preview_url"],state["preview_deployment_url"]) if o]]))
    state_path.write_text(json.dumps(state,indent=2))
    print(json.dumps({"preview_url":state["preview_url"],"production_changed":False}))


if __name__=="__main__":
    main()
