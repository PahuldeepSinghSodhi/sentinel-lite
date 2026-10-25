"""Bounded command completion and private evidence; no fire-and-forget privileges."""
import json
from pathlib import Path
import time


def wait_command(aws, state, command_id, label, timeout=900):
    deadline=time.monotonic()+timeout
    previous=None
    client=aws.client("ssm")
    while time.monotonic()<deadline:
        try:
            result=client.get_command_invocation(CommandId=command_id,InstanceId=state["instance"])
        except client.exceptions.InvocationDoesNotExist:
            time.sleep(1)
            continue
        status=result["Status"]
        if status!=previous:
            print(label+": "+status,flush=True);previous=status
        if status not in {"Pending","InProgress","Delayed","Cancelling"}:
            target=Path.home()/"SentinelRecovery/aws-migration"/(label+"-verified-command.json")
            target.write_text(json.dumps(result,default=str,indent=2))
            if status!="Success":raise RuntimeError(label+" failed; inspect protected command evidence")
            return result
        time.sleep(3)
    client.cancel_command(CommandId=command_id,InstanceIds=[state["instance"]])
    raise RuntimeError(label+" timed out and cancellation was requested")
