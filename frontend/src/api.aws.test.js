import { afterEach, beforeEach, expect, it, vi } from "vitest";

const state = vi.hoisted(() => ({session:null, denied:vi.fn()}));
vi.mock("./cloud",()=>({CLOUD_MODE:true,CLOUD_PROVIDER:"aws",requestSession:async()=>state.session}));
vi.mock("./access",()=>({notifyAccessFailure:state.denied}));

let api, uploadFile, checkUpload;
const response=(body,status=200)=>({ok:status<400,status,json:async()=>body});
beforeEach(async()=>{
  vi.stubEnv("VITE_API_BASE_URL","https://api.example.test");
  state.session={user:{id:"one",email:"one@example.test"},identity_token:"id-one",access_token:"access-one"};
  state.denied.mockClear();
  ({api,uploadFile,checkUpload}=await import("./api"));
});
afterEach(()=>{vi.useRealTimers();vi.unstubAllGlobals();vi.unstubAllEnvs();});

it("authenticates queued operations with the ID token and returns their saved result",async()=>{
  vi.stubGlobal("fetch",vi.fn().mockResolvedValueOnce(response({job_id:"job"},202))
    .mockResolvedValueOnce(response({status:"completed",result_json:{answer:"saved answer"}})));
  expect(await api("/cases/case/questions",{method:"POST",body:JSON.stringify({question:"terms?"})})).toEqual({answer:"saved answer"});
  expect(fetch.mock.calls[0][1].headers.Authorization).toBe("Bearer id-one");
  expect(fetch.mock.calls[0][1].headers["Idempotency-Key"]).toBeTruthy();
  expect(fetch.mock.calls[1][0]).toBe("https://api.example.test/jobs/job");
});

it("rejects empty, oversized and unsupported files before requesting a ticket",async()=>{
  vi.stubGlobal("fetch",vi.fn());
  await expect(uploadFile("case","transactions",new File([],"empty.csv"))).rejects.toThrow("nonempty");
  await expect(uploadFile("case","transactions",new File([new Uint8Array(10485761)],"big.csv"))).rejects.toThrow("10 MiB");
  await expect(uploadFile("case","transactions",new File(["text"],"bad.txt"))).rejects.toThrow("CSV");
  expect(fetch).not.toHaveBeenCalled();
});

it("returns the original validation reason without retrying a failed job",async()=>{
  vi.stubGlobal("fetch",vi.fn().mockResolvedValue(response({status:"failed",error:"Missing required columns: hourly_rate",error_code:"upload_invalid"})));
  await expect(checkUpload("job")).rejects.toMatchObject({message:"Missing required columns: hourly_rate",code:"upload_invalid"});
  expect(fetch).toHaveBeenCalledTimes(1);
});

it("stops foreground waiting at two minutes without failing or resubmitting the upload",async()=>{
  vi.useFakeTimers();
  vi.stubGlobal("fetch",vi.fn().mockResolvedValue(response({status:"queued"})));
  const pending=checkUpload("job");
  await vi.advanceTimersByTimeAsync(120001);
  await expect(pending).resolves.toMatchObject({pending:true,job_id:"job"});
  expect(fetch.mock.calls.every(([url])=>url.endsWith("/jobs/job"))).toBe(true);
});

it("releases an unconfirmed upload after a transfer failure",async()=>{
  vi.stubGlobal("fetch",vi.fn().mockResolvedValueOnce(response({upload_id:"upload",url:"https://bucket.s3.ap-southeast-2.amazonaws.com/",fields:{}}))
    .mockRejectedValueOnce(new TypeError("network failed")).mockResolvedValueOnce(response({},204)));
  await expect(uploadFile("case","transactions",new File(["valid"],"file.csv"))).rejects.toThrow("File transfer failed");
  expect(fetch.mock.calls[2][0]).toMatch(/\/uploads\/upload$/);
  expect(fetch.mock.calls[2][1].method).toBe("DELETE");
});

it("discards an old successful result after the account changes",async()=>{
  let finish;
  vi.stubGlobal("fetch",vi.fn(()=>new Promise(resolve=>{finish=resolve;})));
  const pending=api("/cases");
  await vi.waitFor(()=>expect(finish).toBeTypeOf("function"));
  state.session={user:{id:"two",email:"two@example.test"},identity_token:"id-two"};
  finish(response([{id:"private-old-case"}]));
  await expect(pending).rejects.toThrow("Account changed");
  expect(fetch).toHaveBeenCalledTimes(1);
});

it("keeps the original credential context on access failures",async()=>{
  const origin=state.session;
  vi.stubGlobal("fetch",vi.fn().mockResolvedValue(response({code:"invite_required",detail:"Invitation revoked"},403)));
  await expect(api("/cases")).rejects.toThrow("Invitation revoked");
  expect(state.denied).toHaveBeenCalledWith(expect.objectContaining({code:"invite_required"}),origin);
});

it("sends private upload bytes directly to S3 and confirms the reserved upload",async()=>{
  vi.stubGlobal("fetch",vi.fn().mockResolvedValueOnce(response({upload_id:"upload",url:"https://bucket.s3.ap-southeast-2.amazonaws.com/",fields:{key:"staging/key"}}))
    .mockResolvedValueOnce({ok:true,status:204})
    .mockResolvedValueOnce(response({job_id:"job"},202))
    .mockResolvedValueOnce(response({status:"completed",result_json:{files:{transactions:{filename:"test.csv"}}}})));
  const file=new File(["synthetic"],"test.csv");
  expect((await uploadFile("case","transactions",file)).files.transactions.filename).toBe("test.csv");
  expect(fetch.mock.calls[1][0]).toBe("https://bucket.s3.ap-southeast-2.amazonaws.com/");
  expect(fetch.mock.calls[1][1].body.get("file").name).toBe("test.csv");
  expect(fetch.mock.calls[2][0]).toMatch(/\/uploads\/upload\/confirm$/);
});
