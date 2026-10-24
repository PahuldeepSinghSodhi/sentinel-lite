"""Pass encrypted test credentials to isolated Chrome through stdin, without logs."""
import json
from pathlib import Path
import subprocess
import argparse
from aws_qualify import authenticated
from aws_login_probe import read_session
from recovery import ROOT

base=Path.home()/"SentinelRecovery/aws-migration"
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument("--account",choices=["owner","qualification"],default="qualification")
parser.add_argument("--url")
args=parser.parse_args()
state=json.loads((base/"state.json").read_text())
qualification=json.loads((base/"qualification.json").read_text())
client=authenticated(args.account)  # refresh if needed, retaining DPAPI protection
case=qualification["case_id"]
if args.account=="owner":
    from aws_qualify import request
    case=next(c["id"] for c in request(client,"GET","/cases").json() if c["status"]=="active")
config={"url":args.url or state["preview_url"],"api":state["api_url"],"pool":state["user_pool"],
        "client":state["user_pool_client"],"region":state["region"],"smallCase":case,
        "tokens":read_session(args.account)}
result=subprocess.run(["node","scripts/aws-live-smoke.mjs"],cwd=ROOT/"frontend",input=json.dumps(config),
    text=True,encoding="utf-8",capture_output=True,timeout=240)
if result.returncode:
    print(result.stderr[-2500:]);raise SystemExit(result.returncode)
evidence=json.loads(result.stdout)
(base/"browser-evidence.json").write_text(json.dumps(evidence,indent=2))
print(json.dumps({k:v for k,v in evidence.items() if k!="requestPaths"}))
