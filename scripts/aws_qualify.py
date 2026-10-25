"""Synthetic live workflow against the shadow AWS API, using DPAPI test sessions.

Never reads or deletes owner cases. Only named qualification cases recorded in
the protected local ledger are eligible for cleanup.
"""
import argparse
import concurrent.futures
import csv
import io
import json
from pathlib import Path
import sys
import time
from uuid import uuid4

import requests
from aws_login_probe import read_session
from aws_session import session
from recovery import dpapi, ROOT

BASE = Path.home()/"SentinelRecovery/aws-migration"
STATE = json.loads((BASE/"state.json").read_text())


def authenticated(name):
    tokens = read_session(name)
    import jwt
    if jwt.decode(tokens["IdToken"], options={"verify_signature":False})["exp"] < time.time()+180:
        import boto3
        from botocore import UNSIGNED
        from botocore.config import Config
        result = boto3.client("cognito-idp",region_name=STATE["region"],config=Config(signature_version=UNSIGNED)).initiate_auth(ClientId=STATE["user_pool_client"], AuthFlow="REFRESH_TOKEN_AUTH",
            AuthParameters={"REFRESH_TOKEN":tokens["RefreshToken"]})["AuthenticationResult"]
        tokens.update(result)
        (BASE/(name+"-session.dpapi")).write_bytes(dpapi(json.dumps(tokens).encode()))
    s=requests.Session()
    s.headers["Authorization"]="Bearer "+tokens["IdToken"]
    return s


def request(s, method, path, **kwargs):
    response=s.request(method,STATE["api_url"]+path,timeout=30,**kwargs)
    if response.status_code>=400:
        raise RuntimeError(f"{method} {path}: {response.status_code} {response.text[:300]}")
    return response


def wait_job(s, job_id):
    started=time.monotonic()
    while time.monotonic()-started<600:
        job=request(s,"GET","/jobs/"+job_id).json()
        if job["status"]=="failed":
            raise RuntimeError("Synthetic operation failed: "+str(job["error"]))
        if job["status"]=="completed":
            return job,round(time.monotonic()-started,3)
        time.sleep(1.5)
    raise RuntimeError("Synthetic job did not finish within ten minutes")


def upload(s, case_id, kind, filename, content):
    ticket=request(s,"POST",f"/cases/{case_id}/uploads/{kind}",json={"filename":filename,"size":len(content)}).json()
    uploaded=requests.post(ticket["url"],data=ticket["fields"],files={"file":(filename,content)},timeout=120)
    uploaded.raise_for_status()
    key=str(uuid4())
    route=f"/cases/{case_id}/uploads/{ticket['upload_id']}/confirm"
    job=request(s,"POST",route,headers={"Idempotency-Key":key}).json()
    repeated=request(s,"POST",route,headers={"Idempotency-Key":key}).json()
    assert repeated["job_id"]==job["job_id"]
    return wait_job(s,job["job_id"])[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action",choices=["workflow","stress","owner-ai","cleanup"])
    args=parser.parse_args()
    ledger_path=BASE/"qualification.json"
    ledger=json.loads(ledger_path.read_text())
    if args.action=="cleanup" and all(ledger.get(name+"_deleted",False) for name in ("case_id","stress_case_id")):
        print("Recorded synthetic cases are already removed")
        return
    qa=None if args.action=="owner-ai" else authenticated("qualification")
    results={}
    def save():
        ledger_path.write_text(json.dumps(ledger,indent=2))
    if args.action=="cleanup":
        for name in ("case_id","stress_case_id"):
            if ledger.get(name) and not ledger.get(name+"_deleted"):
                case=request(qa,"GET","/cases/"+ledger[name]).json()
                assert case["name"].startswith("AWS synthetic ")
                request(qa,"DELETE","/cases/"+ledger[name])
                ledger[name+"_deleted"]=True
        save();print("Only recorded synthetic cases removed");return
    if args.action in {"workflow","stress"}:
        stress=args.action=="stress"
        if stress and not ledger.get("stress_case_id"):
            ledger["stress_case_id"]=request(qa,"POST","/cases",json={"name":"AWS synthetic 2400-row capacity"}).json()["id"]
            save()
        case_id=ledger["stress_case_id" if stress else "case_id"]
        case=request(qa,"GET","/cases/"+case_id).json()
        if case["status"]=="draft":
            content=(ROOT/"backend/data/sample_transactions.csv").read_bytes()
            if stress:
                rows=list(csv.DictReader(io.StringIO(content.decode())))
                output=io.StringIO();writer=csv.DictWriter(output,fieldnames=list(rows[0]));writer.writeheader()
                for i in range(2400):
                    row={**rows[i%len(rows)],"transaction_id":f"AWS-QA-{i:05}","invoice_ref":f"AWS-INV-{i//2:05}"}
                    writer.writerow(row)
                content=output.getvalue().encode()
            results["transaction_upload_seconds"]=upload(qa,case_id,"transactions","synthetic.csv",content)
            results["rate_upload_seconds"]=upload(qa,case_id,"rate_card","rates.csv",(ROOT/"backend/data/rate_card.csv").read_bytes())
            from reportlab.pdfgen.canvas import Canvas
            pdf=io.BytesIO();canvas=Canvas(pdf);canvas.drawString(72,750,"Synthetic qualification agreement: payment due within 30 days.");canvas.save()
            results["pdf_upload_seconds"]=upload(qa,case_id,"contract","synthetic-contract.pdf",pdf.getvalue())
            started=time.monotonic()
            result=request(qa,"POST",f"/cases/{case_id}/start").json()
            results["prepare_seconds"]=wait_job(qa,result["job_id"])[1]
            results["prepare_total_seconds"]=round(time.monotonic()-started,3)
        runs=[]
        owner=authenticated("owner")
        for _ in range(3 if stress else 1):
            job=request(qa,"POST",f"/cases/{case_id}/scans").json()
            # A second, real owner session must stay responsive while the worker is busy.
            latencies=[]
            def read_metadata():
                for _ in range(8):
                    started=time.monotonic();request(owner,"GET","/cases");latencies.append(round(time.monotonic()-started,3));time.sleep(.5)
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                reading=pool.submit(read_metadata)
                finished,seconds=wait_job(qa,job["job_id"])
                reading.result()
            current=request(qa,"GET","/cases/"+case_id).json()
            scan=current["scans"][-1]
            if stress:assert scan["transactions_analyzed"]==2400
            runs.append({"job_seconds":seconds,"rows":scan["transactions_analyzed"],"scan_ms":scan["duration_ms"],
                         "findings":len(scan["findings"]),"parallel_case_list_seconds":latencies})
        results["scan_runs"]=runs
        preview=request(qa,"GET",f"/cases/{case_id}/files/contract/original").json()
        content=requests.get(preview["url"],timeout=30);content.raise_for_status();assert content.content.startswith(b"%PDF")
        assert requests.get(preview["url"].split("?")[0],timeout=30).status_code==403
        results["private_pdf_access"]=True
        report=request(qa,"GET",f"/cases/{case_id}/report")
        if report.status_code==202:
            wait_job(qa,report.json()["job_id"])
            report=request(qa,"GET",f"/cases/{case_id}/report")
        content=requests.get(report.json()["url"],timeout=30);content.raise_for_status();assert content.content.startswith(b"%PDF")
        results["report_bytes"]=len(content.content)
        assert request(qa,"GET",f"/cases/{case_id}/source/transactions?row=2").json()["location"]=="CSV row 2"
        ledger[args.action]=results;save();print(json.dumps(results));return
    owner=authenticated("owner")
    assert request(owner,"GET","/me/model").json()["configured"],"Owner must re-enter and test a provider key first"
    cases=request(owner,"GET","/cases").json()
    case_id=next(c["id"] for c in cases if c["status"]=="active")
    response=request(owner,"POST",f"/cases/{case_id}/questions",headers={"Idempotency-Key":str(uuid4())},
        json={"question":"What payment terms are documented? Cite the source and say if unavailable.","top_k":3})
    result,seconds=wait_job(owner,response.json()["job_id"])
    assert result["result_json"].get("answer")
    ledger["owner_ai"]={"seconds":seconds,"answer_saved":True,"sources":len(result["result_json"].get("sources",[]))}
    save();print(json.dumps(ledger["owner_ai"]))


if __name__=="__main__":
    main()
