import { act,fireEvent,render,screen,waitFor } from "@testing-library/react";
import { beforeEach,expect,it,vi } from "vitest";
import DocumentsTab from "./DocumentsTab";
import { uploadFile,checkUpload } from "../api";

vi.mock("../cloud",()=>({CLOUD_MODE:true}));
vi.mock("../api",()=>({api:vi.fn(),uploadFile:vi.fn(),checkUpload:vi.fn(),cancelUpload:vi.fn()}));
const review={id:"case",status:"draft",ready:false,files:{},uploads:{},can_start:false};
beforeEach(()=>vi.clearAllMocks());

it("shows required columns and ends the uploading state on a validation error",async()=>{
  uploadFile.mockRejectedValue(new Error("Missing required columns: hourly_rate"));
  render(<DocumentsTab review={review} onChange={vi.fn()} />);
  fireEvent.change(screen.getByLabelText("Upload transactions"),{target:{files:[new File(["random"],"random.csv")]}});
  expect(await screen.findByRole("alert")).toHaveTextContent("Missing required columns");
  expect(screen.getByLabelText("Upload transactions")).toBeEnabled();
  expect(screen.getByText(/Required columns: vendor_name, role_level, hourly_rate/)).toBeVisible();
});

it("changes progress from transfer to queue to validation",async()=>{
  let progress,finish;
  uploadFile.mockImplementation((id,kind,file,update)=>{progress=update;return new Promise(resolve=>{finish=resolve;});});
  render(<DocumentsTab review={review} onChange={vi.fn()} />);
  fireEvent.change(screen.getByLabelText("Upload transactions"),{target:{files:[new File(["test"],"file.csv")]}});
  act(()=>progress({stage:"queued"}));
  expect(screen.getByRole("status")).toHaveTextContent("Waiting for validation");
  act(()=>progress({stage:"validating"}));
  expect(screen.getByRole("status")).toHaveTextContent("Checking file");
  await act(async()=>finish({}));
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
});

it("clears the spinner before refreshing and reports an accepted-file refresh failure",async()=>{
  let failRefresh;
  uploadFile.mockResolvedValue({});
  const onChange=vi.fn(()=>new Promise((resolve,reject)=>{failRefresh=reject;}));
  render(<DocumentsTab review={review} onChange={onChange} />);
  fireEvent.change(screen.getByLabelText("Upload transactions"),{target:{files:[new File(["ok"],"ok.csv")]}});
  await waitFor(()=>expect(onChange).toHaveBeenCalled());
  expect(screen.getByLabelText("Upload transactions")).toBeEnabled();
  await act(async()=>failRefresh(new Error("offline")));
  expect(screen.getByRole("alert")).toHaveTextContent("Your file was accepted");
});

it("restores a pending upload from case metadata without creating another ticket",async()=>{
  checkUpload.mockResolvedValue({});
  render(<DocumentsTab review={{...review,uploads:{transactions:{status:"queued",job_id:"existing"}}}} onChange={vi.fn()} />);
  expect(screen.getByLabelText("Upload transactions")).toBeDisabled();
  fireEvent.click(screen.getByRole("button",{name:"Check status"}));
  await waitFor(()=>expect(checkUpload).toHaveBeenCalledWith("existing",expect.any(Function)));
  expect(uploadFile).not.toHaveBeenCalled();
});

it("shows retry for a failed sample and never offers to replace its source files",()=>{
  const retry=vi.fn();
  render(<DocumentsTab review={{...review,is_sample:true,job:{status:"failed",error:"Storage limit reached"}}} onTrySample={retry} />);
  fireEvent.click(screen.getByRole("button",{name:"Retry sample"}));
  expect(retry).toHaveBeenCalledTimes(1);
  expect(screen.queryByLabelText("Upload transactions")).not.toBeInTheDocument();
});
