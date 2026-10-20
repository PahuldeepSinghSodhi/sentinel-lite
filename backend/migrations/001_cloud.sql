-- Apply in a dedicated Supabase project after enabling the Vault extension.
-- Run once, then add your own lower-case email to app_invites with role 'admin'.
-- Finally select public.sentinel_before_user_created in Auth > Hooks.

create table if not exists public.app_invites (
  email text primary key check (email = lower(email)),
  role text not null default 'reviewer' check (role in ('admin', 'reviewer')),
  enabled boolean not null default true,
  created_at timestamptz not null default now()
);

create table if not exists public.cases (
  id uuid primary key,
  owner_id uuid not null references auth.users(id),
  name text not null,
  status text not null check (status in ('draft', 'starting', 'active')),
  created_at timestamptz not null default now(),
  started_at timestamptz
);
create index if not exists cases_owner_created on public.cases(owner_id, created_at desc);

create table if not exists public.case_files (
  case_id uuid not null references public.cases(id) on delete cascade,
  kind text not null check (kind in ('transactions', 'rate_card', 'contract')),
  filename text not null,
  extension text not null,
  size bigint not null check (size > 0),
  path text not null unique,
  uploaded_at timestamptz not null default now(),
  primary key (case_id, kind)
);
create table if not exists public.case_artifacts (
  case_id uuid not null references public.cases(id) on delete cascade,
  name text not null,
  path text not null unique,
  size bigint not null check (size >= 0),
  primary key (case_id, name)
);
create table if not exists public.jobs (
  id uuid primary key,
  case_id uuid not null references public.cases(id) on delete cascade,
  owner_id uuid not null references auth.users(id),
  kind text not null check (kind in ('start', 'scan')),
  status text not null default 'queued' check (status in ('queued', 'running', 'completed', 'failed')),
  attempts integer not null default 0,
  leased_until timestamptz,
  result_id uuid,
  error text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists jobs_claim on public.jobs(status, created_at);
create index if not exists jobs_case_created on public.jobs(case_id, created_at desc);
create index if not exists jobs_owner on public.jobs(owner_id);

create table if not exists public.scans (
  id uuid primary key,
  case_id uuid not null references public.cases(id) on delete cascade,
  job_id uuid unique references public.jobs(id) on delete set null,
  created_at timestamptz not null default now(),
  transactions_analyzed integer not null,
  duration_ms integer not null
);
create index if not exists scans_case_created on public.scans(case_id, created_at);
create table if not exists public.findings (
  id uuid primary key,
  scan_id uuid not null references public.scans(id) on delete cascade,
  ordinal integer not null,
  data_json jsonb not null,
  decision text check (decision in ('investigate', 'approved_exception', 'false_alarm')),
  note text not null default '',
  decided_at timestamptz,
  unique (scan_id, ordinal)
);
create index if not exists findings_scan on public.findings(scan_id);
create table if not exists public.investigations (
  finding_id uuid primary key references public.findings(id) on delete cascade,
  payload_json jsonb not null
);
create table if not exists public.questions (
  id uuid primary key,
  case_id uuid not null references public.cases(id) on delete cascade,
  created_at timestamptz not null default now(),
  question text not null,
  answer text not null,
  sources_json jsonb not null,
  confidence_json jsonb not null,
  presentation_json jsonb
);
create index if not exists questions_case_created on public.questions(case_id, created_at);
create table if not exists public.model_settings (
  owner_id uuid primary key references auth.users(id) on delete cascade,
  provider text not null check (provider in ('ollama_cloud', 'groq', 'openai')),
  model text not null,
  vault_id uuid not null,
  updated_at timestamptz not null default now()
);

-- Only the trusted API uses privileged DB/Storage credentials. RLS is a
-- second barrier if a future direct-to-Supabase browser feature is added.
alter table public.app_invites enable row level security;
alter table public.cases enable row level security;
alter table public.case_files enable row level security;
alter table public.case_artifacts enable row level security;
alter table public.jobs enable row level security;
alter table public.scans enable row level security;
alter table public.findings enable row level security;
alter table public.investigations enable row level security;
alter table public.questions enable row level security;
alter table public.model_settings enable row level security;

create policy cases_owner on public.cases for all to authenticated
  using (owner_id = (select auth.uid())) with check (owner_id = (select auth.uid()));
create policy files_owner on public.case_files for all to authenticated
  using (exists (select 1 from public.cases c where c.id = case_id and c.owner_id = (select auth.uid())))
  with check (exists (select 1 from public.cases c where c.id = case_id and c.owner_id = (select auth.uid())));
create policy artifacts_owner on public.case_artifacts for all to authenticated
  using (exists (select 1 from public.cases c where c.id = case_id and c.owner_id = (select auth.uid())))
  with check (exists (select 1 from public.cases c where c.id = case_id and c.owner_id = (select auth.uid())));
create policy jobs_owner on public.jobs for select to authenticated
  using (owner_id = (select auth.uid()));
create policy scans_owner on public.scans for select to authenticated
  using (exists (select 1 from public.cases c where c.id = case_id and c.owner_id = (select auth.uid())));
create policy findings_owner on public.findings for select to authenticated
  using (exists (select 1 from public.scans s join public.cases c on c.id = s.case_id
                 where s.id = scan_id and c.owner_id = (select auth.uid())));
create policy investigations_owner on public.investigations for select to authenticated
  using (exists (select 1 from public.findings f join public.scans s on s.id = f.scan_id
                 join public.cases c on c.id = s.case_id
                 where f.id = finding_id and c.owner_id = (select auth.uid())));
create policy questions_owner on public.questions for select to authenticated
  using (exists (select 1 from public.cases c where c.id = case_id and c.owner_id = (select auth.uid())));
create policy model_settings_owner on public.model_settings for select to authenticated
  using (owner_id = (select auth.uid()));

-- The browser talks only to FastAPI, never directly to these tables through
-- PostgREST. RLS remains defense in depth, while explicit privilege removal
-- prevents a revoked invite with an unexpired JWT from bypassing the API.
revoke all on table public.app_invites, public.cases, public.case_files,
  public.case_artifacts, public.jobs, public.scans, public.findings,
  public.investigations, public.questions, public.model_settings
  from public, anon, authenticated;

-- Fail closed for new OAuth accounts. Existing users are checked on every API call.
create or replace function public.sentinel_before_user_created(event jsonb)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare invited boolean;
begin
  select enabled into invited from public.app_invites
    where email = lower(coalesce(event->'user'->>'email', ''));
  if coalesce(invited, false) then return '{}'::jsonb; end if;
  return jsonb_build_object('error', jsonb_build_object(
    'http_code', 403, 'message', 'This email is not invited to Sentinel.'));
end;
$$;
revoke execute on function public.sentinel_before_user_created(jsonb) from public, anon, authenticated;
grant execute on function public.sentinel_before_user_created(jsonb) to supabase_auth_admin;

insert into storage.buckets (id, name, public, file_size_limit)
values ('sentinel-private', 'sentinel-private', false, 41943040)
on conflict (id) do nothing;
