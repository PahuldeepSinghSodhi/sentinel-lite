"""Create the HTTPS/private API integration. Never changes the existing Vercel site."""
import json
from pathlib import Path
from uuid import uuid4

from aws_session import ACCOUNT,REGION,session


def main():
    path=Path.home()/"SentinelRecovery/aws-migration/state.json"
    state=json.loads(path.read_text())
    aws=session()

    def save(name,value):
        state[name]=value
        path.write_text(json.dumps(state,indent=2))
        print("Recorded "+name,flush=True)

    discovery=aws.client("servicediscovery")
    if "namespace_operation" not in state:
        operation=discovery.create_http_namespace(Name="sentinel",CreatorRequestId=str(uuid4()),Description="Sentinel private API discovery",Tags=[{"Key":"Application","Value":"Sentinel"}])
        save("namespace_operation",operation["OperationId"])
    if "namespace" not in state:
        operation=discovery.get_operation(OperationId=state["namespace_operation"])["Operation"]
        if operation["Status"]!="SUCCESS":
            print("Cloud Map namespace is provisioning; rerun when ready")
            return
        save("namespace",operation["Targets"]["NAMESPACE"])
    if "discovery_service" not in state:
        service=discovery.create_service(Name="api",NamespaceId=state["namespace"],Type="HTTP",CreatorRequestId=str(uuid4()),
            HealthCheckCustomConfig={"FailureThreshold":1},Tags=[{"Key":"Application","Value":"Sentinel"}])["Service"]
        save("discovery_service",service["Id"])
        save("discovery_arn",service["Arn"])
    if "discovery_instance" not in state:
        operation=discovery.register_instance(ServiceId=state["discovery_service"],InstanceId="primary",Attributes={
            "AWS_INSTANCE_IPV4":state["private_ip"],"AWS_INSTANCE_PORT":"8000","AWS_INIT_HEALTH_STATUS":"UNHEALTHY"})
        save("discovery_instance",operation["OperationId"])
    gateway=aws.client("apigatewayv2")
    if "vpc_link" not in state:
        link=gateway.create_vpc_link(Name="sentinel-private",SubnetIds=[state["private_a"],state["private_b"]],SecurityGroupIds=[state["link_sg"]],Tags={"Application":"Sentinel"})
        save("vpc_link",link["VpcLinkId"])
    origins=["https://sentinel-document-intelligence.vercel.app"]
    if state.get("preview_url"):
        origins.append(state["preview_url"])
    origins=list(dict.fromkeys(origins+state.get("preview_origins",[])))
    if "api" not in state:
        api=gateway.create_api(Name="sentinel",ProtocolType="HTTP",CorsConfiguration={"AllowOrigins":origins,
            "AllowMethods":["GET","POST","PUT","PATCH","DELETE","OPTIONS"],"AllowHeaders":["authorization","content-type","idempotency-key"],"MaxAge":300},Tags={"Application":"Sentinel"})
        save("api",api["ApiId"])
        save("api_url",api["ApiEndpoint"])
    gateway.update_api(ApiId=state["api"],CorsConfiguration={"AllowOrigins":origins,
        "AllowMethods":["GET","POST","PUT","PATCH","DELETE","OPTIONS"],"AllowHeaders":["authorization","content-type","idempotency-key"],"MaxAge":300})
    if "integration" not in state:
        integration=gateway.create_integration(ApiId=state["api"],IntegrationType="HTTP_PROXY",IntegrationMethod="ANY",
            IntegrationUri=state["discovery_arn"],ConnectionType="VPC_LINK",ConnectionId=state["vpc_link"],PayloadFormatVersion="1.0",
            TimeoutInMillis=29000,RequestParameters={"overwrite:path":"$request.path"})
        save("integration",integration["IntegrationId"])
    if "authorizer" not in state:
        authorizer=gateway.create_authorizer(ApiId=state["api"],Name="sentinel-cognito",AuthorizerType="JWT",IdentitySource=["$request.header.Authorization"],
            JwtConfiguration={"Audience":[state["user_pool_client"]],"Issuer":f"https://cognito-idp.{REGION}.amazonaws.com/{state['user_pool']}"})
        save("authorizer",authorizer["AuthorizerId"])
    routes={r["RouteKey"]:r for r in gateway.get_routes(ApiId=state["api"])["Items"]}
    for key in ("GET /","GET /health","OPTIONS /{proxy+}","ANY /{proxy+}"):
        if key not in routes:
            authorization={"AuthorizationType":"JWT","AuthorizerId":state["authorizer"]} if key.startswith("ANY") else {"AuthorizationType":"NONE"}
            gateway.create_route(ApiId=state["api"],RouteKey=key,Target="integrations/"+state["integration"],**authorization)
    if "stage" not in state:
        logs=aws.client("logs",region_name=state["log_region"])
        try:
            logs.create_log_group(logGroupName="/sentinel/api-access",tags={"Application":"Sentinel"})
        except logs.exceptions.ResourceAlreadyExistsException:
            pass
        logs.put_retention_policy(logGroupName="/sentinel/api-access",retentionInDays=7)
        gateway.create_stage(ApiId=state["api"] ,StageName="$default",AutoDeploy=True,
            DefaultRouteSettings={"ThrottlingBurstLimit":20,"ThrottlingRateLimit":5},
            AccessLogSettings={"DestinationArn":f"arn:aws:logs:{state['log_region']}:{ACCOUNT}:log-group:/sentinel/api-access",
            "Format":json.dumps({"requestId":"$context.requestId","route":"$context.routeKey","status":"$context.status","bytes":"$context.responseLength"})})
        save("stage","$default")
    print(json.dumps({"api_url":state["api_url"],"vpc_link_status":gateway.get_vpc_link(VpcLinkId=state["vpc_link"])["VpcLinkStatus"]}))


if __name__=="__main__":
    main()
