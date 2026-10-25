"""Run installed Chrome sample/upload checks without exposing credentials."""
import argparse
import json
from pathlib import Path
import subprocess
from aws_sample_upload_probe import BASE,FOLDER,credentials
from recovery import ROOT

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument("--url");parser.add_argument("--fresh",action="store_true");args=parser.parse_args()
if args.fresh:
    import aws_sample_upload_probe
    aws_sample_upload_probe.FOLDER=FOLDER/"secondary"
state=json.loads((BASE/"state.json").read_text())
after=json.loads((FOLDER/"after.json").read_text())
config={"url":args.url or state["preview_url"],"api":state["api_url"],"pool":state["user_pool"],"client":state["user_pool_client"],
    "tokens":credentials(),"sampleCase":after["sample_case"],"customCase":after["custom_case"],"fresh":args.fresh,
    "csv":(ROOT/"backend/data/sample_transactions.csv").read_text(),
    "screenshotPath":str(FOLDER/"upload-validation-browser.png")}
r=subprocess.run(["node","scripts/sample-upload-smoke.mjs"],cwd=ROOT/"frontend",input=json.dumps(config),text=True,encoding="utf-8",capture_output=True,timeout=240)
if r.returncode:
    print(r.stderr[-2200:]);raise SystemExit(r.returncode)
evidence=json.loads(r.stdout)
label=("production" if config["url"]=="https://sentinel-document-intelligence.vercel.app" else "preview")+("-fresh" if args.fresh else "")
(FOLDER/(label+"-browser.json")).write_text(json.dumps(evidence,indent=2))
print(json.dumps({k:v for k,v in evidence.items() if k!="requests"}))
