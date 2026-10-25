"""Keep a protected off-account copy of the newest encrypted AWS recovery set.

The data stays encrypted. Its recovery key is protected with Windows DPAPI;
provider credentials are never included. Keep this Windows profile recoverable.
"""
import hashlib
import json
from pathlib import Path

from aws_session import session
from recovery import dpapi, protect_dir


def main():
    base=Path.home()/"SentinelRecovery/aws-migration"
    state=json.loads((base/"state.json").read_text())
    aws=session();s3=aws.client("s3");bucket=state["backup_bucket"]
    objects=[o for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket,Prefix="daily/")
        for o in page.get("Contents",[]) if o["Key"].endswith("/COMPLETE.json")]
    completed=max(objects,key=lambda o:o["LastModified"])
    prefix=completed["Key"].removesuffix("COMPLETE.json")
    target=protect_dir(base/"off-account"/prefix.strip("/").split("/")[-1])
    files=[o for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket,Prefix=prefix) for o in page.get("Contents",[])]
    hashes={}
    for obj in files:
        relative=Path(obj["Key"].removeprefix(prefix))
        output=(target/relative).resolve()
        if target.resolve() not in output.parents:
            raise ValueError("Unexpected recovery object path")
        output.parent.mkdir(parents=True,exist_ok=True)
        s3.download_file(bucket,obj["Key"],str(output))
        if output.stat().st_size!=obj["Size"]:
            raise RuntimeError("Recovery download size mismatch")
        hashes[relative.as_posix()]=hashlib.sha256(output.read_bytes()).hexdigest()
    complete=json.loads((target/"COMPLETE.json").read_text())
    if hashes["manifest.enc"]!=complete["manifest_sha256"]:
        raise RuntimeError("Recovery download hash mismatch")
    key=bytes.fromhex(aws.client("secretsmanager").get_secret_value(SecretId=state["backup_secret"])["SecretString"])
    (target/"recovery-key.dpapi").write_bytes(dpapi(key))
    (target/"download-hashes.json").write_text(json.dumps(hashes,indent=2))
    state["off_account_backup"]=str(target)
    (base/"state.json").write_text(json.dumps(state,indent=2))
    print(json.dumps({"encrypted_off_account_copy":str(target),"files_verified":len(files),"key":"Windows-protected"}))


if __name__=="__main__":main()
