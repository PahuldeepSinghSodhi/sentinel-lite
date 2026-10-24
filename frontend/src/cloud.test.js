import { afterEach, expect, it, vi } from "vitest";

const createClient = vi.hoisted(() => vi.fn());
vi.mock("@supabase/supabase-js", () => ({ createClient }));

afterEach(() => { vi.unstubAllEnvs(); vi.resetModules(); });

it("keeps local mode independent of Supabase and sends no auth headers", async () => {
  vi.stubEnv("VITE_SENTINEL_MODE", "local");
  const { CLOUD_MODE, supabase, requestSession, authHeaders } = await import("./cloud");
  expect(CLOUD_MODE).toBe(false);
  expect(supabase).toBeNull();
  expect(await requestSession()).toBeNull();
  expect(await authHeaders()).toEqual({});
  expect(createClient).not.toHaveBeenCalled();
});
