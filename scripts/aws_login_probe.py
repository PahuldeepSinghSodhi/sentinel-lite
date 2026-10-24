"""Native Cognito test login. Challenge/session credentials are Windows-encrypted locally."""
import argparse
import json
from pathlib import Path
import time

from aws_session import session
from recovery import dpapi

BASE=Path.home()/"SentinelRecovery/aws-migration"


def read_session(name="owner"):
    return json.loads(dpapi((BASE/(name+"-session.dpapi")).read_bytes(),decrypt=True))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action",choices=["send","verify"])
    parser.add_argument("--name",default="owner")
    parser.add_argument("--email")
    parser.add_argument("--code")
    args=parser.parse_args()
    assert args.name in {"owner","qualification"}
    state=json.loads((BASE/"state.json").read_text())
    client=session().client("cognito-idp")
    challenge_path=BASE/(args.name+"-challenge.dpapi")
    if args.action=="send":
        email=args.email or state["email_sender"]
        result=client.initiate_auth(ClientId=state["user_pool_client"],AuthFlow="USER_AUTH",
            AuthParameters={"USERNAME":email,"PREFERRED_CHALLENGE":"EMAIL_OTP"})
        if result["ChallengeName"]!="EMAIL_OTP":
            raise RuntimeError("Unexpected login challenge")
        challenge={"session":result["Session"],"username":result.get("ChallengeParameters",{}).get("USERNAME",email),"created_at":time.time()}
        challenge_path.write_bytes(dpapi(json.dumps(challenge).encode()))
        print("Cognito email code sent; challenge encrypted locally")
    else:
        challenge=json.loads(dpapi(challenge_path.read_bytes(),decrypt=True))
        if not args.code or not args.code.isdigit() or not 6<=len(args.code)<=8:
            raise ValueError("Expected the email verification code")
        result=client.respond_to_auth_challenge(ClientId=state["user_pool_client"],ChallengeName="EMAIL_OTP",Session=challenge["session"],
            ChallengeResponses={"USERNAME":challenge["username"],"EMAIL_OTP_CODE":args.code})["AuthenticationResult"]
        (BASE/(args.name+"-session.dpapi")).write_bytes(dpapi(json.dumps(result).encode()))
        challenge_path.unlink(missing_ok=True)
        print("Native Cognito sign-in succeeded; test session encrypted locally")


if __name__=="__main__":
    main()
