"""Create only Sentinel's isolated AWS foundation under the approved Free-plan project.

State contains resource IDs, never passwords. Existing application hosting is untouched.
Run without --compute to prepare private networking/storage; --compute starts credit usage.
"""
import argparse
import json
from pathlib import Path
import secrets

from botocore.exceptions import ClientError

from aws_session import ACCOUNT, REGION, session
from recovery import protect_dir

BASE = protect_dir(Path.home() / "SentinelRecovery/aws-migration")
STATE = BASE / "state.json"
TAGS = [{"Key": "Application", "Value": "Sentinel"}, {"Key": "Purpose", "Value": "portfolio-migration"}]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compute", action="store_true")
    args = parser.parse_args()
    aws = session()
    state = json.loads(STATE.read_text()) if STATE.exists() else {"account": ACCOUNT, "region": REGION}
    assert state["account"] == ACCOUNT and state["region"] == REGION

    def save(name, value):
        state[name] = value
        temporary = STATE.with_suffix(".tmp")
        temporary.write_text(json.dumps(state, indent=2))
        temporary.replace(STATE)
        print("Recorded " + name, flush=True)
        return value

    ec2 = aws.client("ec2")
    if "vpc" not in state:
        save("vpc", ec2.create_vpc(CidrBlock="10.48.0.0/16", TagSpecifications=[{"ResourceType": "vpc", "Tags": TAGS}])["Vpc"]["VpcId"])
    ec2.modify_vpc_attribute(VpcId=state["vpc"], EnableDnsSupport={"Value": True})
    ec2.modify_vpc_attribute(VpcId=state["vpc"], EnableDnsHostnames={"Value": True})
    zones = [z["ZoneName"] for z in ec2.describe_availability_zones(Filters=[{"Name": "state", "Values": ["available"]}])["AvailabilityZones"]]
    for name, cidr, zone in (("public_subnet", "10.48.1.0/24", zones[0]),
                             ("private_a", "10.48.11.0/24", zones[0]),
                             ("private_b", "10.48.12.0/24", zones[1])):
        if name not in state:
            save(name, ec2.create_subnet(VpcId=state["vpc"], CidrBlock=cidr, AvailabilityZone=zone,
                                       TagSpecifications=[{"ResourceType": "subnet", "Tags": TAGS + [{"Key": "Name", "Value": "sentinel-" + name}]}])["Subnet"]["SubnetId"])
    if "internet_gateway" not in state:
        save("internet_gateway", ec2.create_internet_gateway(TagSpecifications=[{"ResourceType": "internet-gateway", "Tags": TAGS}])["InternetGateway"]["InternetGatewayId"])
        ec2.attach_internet_gateway(InternetGatewayId=state["internet_gateway"], VpcId=state["vpc"])
    if "public_route_table" not in state:
        save("public_route_table", ec2.create_route_table(VpcId=state["vpc"], TagSpecifications=[{"ResourceType": "route-table", "Tags": TAGS}])["RouteTable"]["RouteTableId"])
        ec2.create_route(RouteTableId=state["public_route_table"], DestinationCidrBlock="0.0.0.0/0", GatewayId=state["internet_gateway"])
        ec2.associate_route_table(RouteTableId=state["public_route_table"], SubnetId=state["public_subnet"])
    for name in ("app_sg", "database_sg", "link_sg"):
        if name not in state:
            save(name, ec2.create_security_group(GroupName="sentinel-" + name, Description="Sentinel private " + name,
                                                VpcId=state["vpc"], TagSpecifications=[{"ResourceType": "security-group", "Tags": TAGS}])["GroupId"])
    if "security_configured" not in state:
        # These are newly created, dedicated groups, never default/shared groups.
        for key in ("app_sg", "database_sg", "link_sg"):
            group = ec2.describe_security_groups(GroupIds=[state[key]])["SecurityGroups"][0]
            if group["IpPermissionsEgress"]:
                ec2.revoke_security_group_egress(GroupId=state[key], IpPermissions=group["IpPermissionsEgress"])

        def peer(port, group):
            return {"IpProtocol": "tcp", "FromPort": port, "ToPort": port,
                    "UserIdGroupPairs": [{"GroupId": state[group]}]}

        for group, rules in (("app_sg", [peer(8000, "link_sg")]), ("database_sg", [peer(5432, "app_sg")])):
            try:
                ec2.authorize_security_group_ingress(GroupId=state[group], IpPermissions=rules)
            except ClientError as exc:
                if exc.response["Error"]["Code"] != "InvalidPermission.Duplicate":
                    raise
        ec2.authorize_security_group_egress(GroupId=state["app_sg"], IpPermissions=[
            {"IpProtocol": "tcp", "FromPort": port, "ToPort": port, "IpRanges": [{"CidrIp": "0.0.0.0/0"}]} for port in (80, 443)] + [peer(5432, "database_sg")])
        ec2.authorize_security_group_egress(GroupId=state["link_sg"], IpPermissions=[peer(8000, "app_sg")])
        save("security_configured", True)

    bucket = state.get("bucket") or f"sentinel-private-{ACCOUNT}-{REGION}"
    s3 = aws.client("s3")
    if "bucket" not in state:
        try:
            s3.create_bucket(Bucket=bucket, CreateBucketConfiguration={"LocationConstraint": REGION})
        except ClientError as exc:
            if exc.response["Error"]["Code"] != "BucketAlreadyOwnedByYou":
                raise
        save("bucket", bucket)
    s3.put_public_access_block(Bucket=bucket, PublicAccessBlockConfiguration={
        "BlockPublicAcls": True, "IgnorePublicAcls": True, "BlockPublicPolicy": True, "RestrictPublicBuckets": True})
    s3.put_bucket_ownership_controls(Bucket=bucket, OwnershipControls={"Rules": [{"ObjectOwnership": "BucketOwnerEnforced"}]})
    s3.put_bucket_encryption(Bucket=bucket, ServerSideEncryptionConfiguration={"Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]})
    s3.put_bucket_tagging(Bucket=bucket, Tagging={"TagSet": TAGS})
    s3.put_bucket_policy(Bucket=bucket, Policy=json.dumps({"Version": "2012-10-17", "Statement": [{
        "Sid": "RequireTLS", "Effect": "Deny", "Principal": "*", "Action": "s3:*",
        "Resource": [f"arn:aws:s3:::{bucket}", f"arn:aws:s3:::{bucket}/*"], "Condition": {"Bool": {"aws:SecureTransport": "false"}}}]}))
    s3.put_bucket_cors(Bucket=bucket, CORSConfiguration={"CORSRules": [{
        "AllowedOrigins": list(dict.fromkeys(["https://sentinel-document-intelligence.vercel.app",*state.get("preview_origins",[])])),
        "AllowedMethods": ["GET", "HEAD", "POST"], "AllowedHeaders": ["*"], "ExposeHeaders": ["ETag"], "MaxAgeSeconds": 300}]})
    ecr = aws.client("ecr")
    if "repository" not in state:
        try:
            repository = ecr.create_repository(repositoryName="sentinel", imageTagMutability="IMMUTABLE",
                                               encryptionConfiguration={"encryptionType": "AES256"}, tags=TAGS)["repository"]
        except ecr.exceptions.RepositoryAlreadyExistsException:
            repository = ecr.describe_repositories(repositoryNames=["sentinel"])["repositories"][0]
        save("repository", repository["repositoryUri"])
    log_region = state.get("log_region", REGION)
    try:
        aws.client("logs", region_name=log_region).create_log_group(logGroupName="/sentinel/application", tags={"Application": "Sentinel"})
    except ClientError as exc:
        if exc.response["Error"]["Code"] not in ("ResourceAlreadyExistsException",):
            if log_region != REGION:
                raise
            log_region = "us-east-1"
            try:
                aws.client("logs", region_name=log_region).create_log_group(logGroupName="/sentinel/application", tags={"Application": "Sentinel"})
            except ClientError as second:
                if second.response["Error"]["Code"] != "ResourceAlreadyExistsException":
                    raise
    aws.client("logs", region_name=log_region).put_retention_policy(logGroupName="/sentinel/application", retentionInDays=7)
    save("log_region", log_region)

    iam = aws.client("iam")
    try:
        role = iam.get_role(RoleName="SentinelRuntime")["Role"]
    except iam.exceptions.NoSuchEntityException:
        role=iam.create_role(RoleName="SentinelRuntime",Path="/sentinel/",AssumeRolePolicyDocument=json.dumps({
            "Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"ec2.amazonaws.com"},"Action":"sts:AssumeRole"}]}),Tags=TAGS)["Role"]
    secret_base = f"arn:aws:secretsmanager:{REGION}:{ACCOUNT}:secret:sentinel"
    policy = {"Version": "2012-10-17", "Statement": [
        {"Effect": "Allow", "Action": ["s3:ListBucket", "s3:GetBucketLocation"], "Resource": f"arn:aws:s3:::{bucket}"},
        {"Effect": "Allow", "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"], "Resource": f"arn:aws:s3:::{bucket}/*"},
        {"Effect": "Allow", "Action": ["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"], "Resource": [secret_base + "/database-*", secret_base + "/providers/*"]},
        {"Effect": "Allow", "Action": ["secretsmanager:CreateSecret", "secretsmanager:PutSecretValue", "secretsmanager:DeleteSecret", "secretsmanager:RestoreSecret", "secretsmanager:TagResource"], "Resource": secret_base + "/providers/*"},
        {"Effect": "Allow", "Action": "ecr:GetAuthorizationToken", "Resource": "*"},
        {"Effect": "Allow", "Action": ["ecr:BatchCheckLayerAvailability", "ecr:GetDownloadUrlForLayer", "ecr:BatchGetImage"], "Resource": f"arn:aws:ecr:{REGION}:{ACCOUNT}:repository/sentinel"},
        {"Effect": "Allow", "Action": ["logs:CreateLogStream", "logs:PutLogEvents", "logs:DescribeLogStreams"], "Resource": f"arn:aws:logs:{log_region}:{ACCOUNT}:log-group:/sentinel/application:*"},
        {"Effect": "Allow", "Action": "cloudwatch:PutMetricData", "Resource": "*", "Condition": {"StringEquals": {"cloudwatch:namespace": "Sentinel"}}},
    ]}
    iam.put_role_policy(RoleName="SentinelRuntime", PolicyName="SentinelResources", PolicyDocument=json.dumps(policy))
    iam.attach_role_policy(RoleName="SentinelRuntime", PolicyArn="arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore")
    try:
        profile = iam.get_instance_profile(InstanceProfileName="SentinelRuntime")["InstanceProfile"]
    except iam.exceptions.NoSuchEntityException:
        profile = iam.create_instance_profile(InstanceProfileName="SentinelRuntime", Path="/sentinel/")["InstanceProfile"]
    if not profile.get("Roles"):
        iam.add_role_to_instance_profile(InstanceProfileName="SentinelRuntime", RoleName="SentinelRuntime")
    save("instance_profile", profile["Arn"])
    save("runtime_role", role["Arn"])
    if not args.compute:
        print("Private foundation ready; no compute launched", flush=True)
        return

    # Starting compute was explicitly authorized under the verified Free-plan credits.
    rds = aws.client("rds")
    if "db_subnet_group" not in state:
        rds.create_db_subnet_group(DBSubnetGroupName="sentinel-private", DBSubnetGroupDescription="Sentinel private database subnets",
                                   SubnetIds=[state["private_a"], state["private_b"]], Tags=TAGS)
        save("db_subnet_group", "sentinel-private")
    if "bootstrap_secret" not in state:
        secret = aws.client("secretsmanager").create_secret(Name="sentinel/bootstrap/database", SecretString=json.dumps({
            "username": "sentinel_admin", "password": secrets.token_urlsafe(36), "dbname": "sentinel", "port": 5432}), Tags=TAGS)
        save("bootstrap_secret", secret["ARN"])
    if "database" not in state:
        master = json.loads(aws.client("secretsmanager").get_secret_value(SecretId=state["bootstrap_secret"])["SecretString"])
        versions = rds.describe_db_engine_versions(Engine="postgres", DefaultOnly=False)["DBEngineVersions"]
        versions = [v["EngineVersion"] for v in versions if v["EngineVersion"].startswith("17.") and v["Status"] == "available"]
        version = max(versions, key=lambda v: tuple(map(int, v.split("."))))
        rds.create_db_instance(DBInstanceIdentifier="sentinel-postgres", DBName="sentinel", Engine="postgres", EngineVersion=version,
                               DBInstanceClass="db.t4g.micro", AllocatedStorage=20, StorageType="gp2", StorageEncrypted=True,
                               MasterUsername=master["username"], MasterUserPassword=master["password"],
                               DBSubnetGroupName=state["db_subnet_group"], VpcSecurityGroupIds=[state["database_sg"]],
                               PubliclyAccessible=False, MultiAZ=False, BackupRetentionPeriod=1, DeletionProtection=True,
                               AutoMinorVersionUpgrade=True, CopyTagsToSnapshot=True, EnablePerformanceInsights=False, Tags=TAGS)
        save("database", "sentinel-postgres")
    if "instance" not in state:
        ami = aws.client("ssm").get_parameter(Name="/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64")["Parameter"]["Value"]
        image = ec2.describe_images(ImageIds=[ami])["Images"][0]
        if image["OwnerId"] != "137112412989" or image["Architecture"] != "x86_64":
            raise RuntimeError("Unexpected Amazon Linux image owner or architecture")
        bootstrap = """#!/bin/bash
set -euo pipefail
dnf install -y docker
systemctl enable --now docker
systemctl enable --now amazon-ssm-agent
install -d -m 700 /opt/sentinel
"""
        instance = ec2.run_instances(ImageId=ami, InstanceType="t3.small", MinCount=1, MaxCount=1,
            ClientToken="sentinel-migration-api-v1", IamInstanceProfile={"Arn": state["instance_profile"]},
            CreditSpecification={"CpuCredits": "standard"}, MetadataOptions={"HttpTokens": "required", "HttpEndpoint": "enabled", "HttpPutResponseHopLimit": 2},
            BlockDeviceMappings=[{"DeviceName": image["RootDeviceName"], "Ebs": {"VolumeSize": 20, "VolumeType": "gp3", "Encrypted": True, "DeleteOnTermination": True}}],
            NetworkInterfaces=[{"DeviceIndex": 0, "SubnetId": state["public_subnet"], "AssociatePublicIpAddress": True, "Groups": [state["app_sg"]]}],
            UserData=bootstrap, TagSpecifications=[{"ResourceType": "instance", "Tags": TAGS + [{"Key": "Name", "Value": "sentinel-api-worker"}]}, {"ResourceType": "volume", "Tags": TAGS}])["Instances"][0]
        save("instance", instance["InstanceId"])
        save("private_ip", instance["PrivateIpAddress"])
    print("Compute provisioning requested; wait for readiness before deployment", flush=True)


if __name__ == "__main__":
    main()
