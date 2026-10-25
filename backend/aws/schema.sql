-- Dedicated RDS application schema. No Supabase Auth, Vault or Storage schemas.
CREATE TABLE IF NOT EXISTS public.app_users (
 id uuid PRIMARY KEY, email text NOT NULL UNIQUE, email_verified boolean NOT NULL,
 disabled boolean NOT NULL DEFAULT false, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS public.auth_identities (
 issuer text NOT NULL, subject text NOT NULL, app_user_id uuid NOT NULL REFERENCES public.app_users(id),
 PRIMARY KEY (issuer,subject), UNIQUE (issuer,app_user_id)
);
create table if not exists public.app_invites (
  email text primary key check (email = lower(email)),
  role text not null default 'reviewer' check (role in ('admin', 'reviewer')),
  enabled boolean not null default true,
  created_at timestamptz not null default now()
);

create table if not exists public.cases (
  id uuid primary key,
  owner_id uuid not null references public.app_users(id),
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
  owner_id uuid not null references public.app_users(id),
  kind text not null check (kind in ('start', 'scan', 'upload', 'question', 'investigate', 'report')),
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
  owner_id uuid primary key references public.app_users(id) on delete cascade,
  provider text not null check (provider in ('ollama_cloud', 'groq', 'openai')),
  model text not null,
  secret_id text not null,
  updated_at timestamptz not null default now()
);


ALTER TABLE public.cases ADD COLUMN IF NOT EXISTS revision bigint NOT NULL DEFAULT 0;
ALTER TABLE public.case_artifacts ADD COLUMN IF NOT EXISTS revision bigint;
ALTER TABLE public.jobs ADD COLUMN IF NOT EXISTS payload_json jsonb NOT NULL DEFAULT '{}';
ALTER TABLE public.jobs ADD COLUMN IF NOT EXISTS result_json jsonb;
ALTER TABLE public.jobs ADD COLUMN IF NOT EXISTS request_key text;
ALTER TABLE public.jobs ADD COLUMN IF NOT EXISTS error_code text;
ALTER TABLE public.cases ADD COLUMN IF NOT EXISTS sample_version text;
CREATE UNIQUE INDEX IF NOT EXISTS cases_one_sample_per_owner ON public.cases(owner_id) WHERE sample_version IS NOT NULL;
ALTER TABLE public.jobs DROP CONSTRAINT IF EXISTS jobs_kind_check;
ALTER TABLE public.jobs ADD CONSTRAINT jobs_kind_check CHECK (kind IN ('start','scan','upload','question','investigate','report','demo'));
CREATE UNIQUE INDEX IF NOT EXISTS jobs_request_key ON public.jobs(owner_id,request_key) WHERE request_key IS NOT NULL;
CREATE TABLE IF NOT EXISTS public.uploads (
 id uuid PRIMARY KEY, case_id uuid NOT NULL REFERENCES public.cases(id) ON DELETE CASCADE,
 owner_id uuid NOT NULL REFERENCES public.app_users(id), kind text NOT NULL,
 filename text NOT NULL, extension text NOT NULL, size bigint NOT NULL CHECK (size > 0 AND size <= 10485760),
 path text NOT NULL UNIQUE, status text NOT NULL CHECK (status IN ('reserved','queued','completed','expired','failed')),
 created_at timestamptz NOT NULL DEFAULT now(), expires_at timestamptz NOT NULL DEFAULT now()+interval '15 minutes'
);
CREATE UNIQUE INDEX IF NOT EXISTS uploads_pending_kind ON public.uploads(case_id,kind) WHERE status IN ('reserved','queued');
ALTER TABLE public.uploads ADD COLUMN IF NOT EXISTS error text;
ALTER TABLE public.uploads ADD COLUMN IF NOT EXISTS error_code text;
CREATE TABLE IF NOT EXISTS public.worker_status (name text PRIMARY KEY, updated_at timestamptz NOT NULL, ready boolean NOT NULL);
CREATE TABLE IF NOT EXISTS public.recovery_model_preferences (
 owner_id uuid PRIMARY KEY REFERENCES public.app_users(id), provider text NOT NULL, model text NOT NULL, updated_at timestamptz
);
CREATE OR REPLACE FUNCTION public.sentinel_case_revision() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE target uuid;
BEGIN
 IF TG_TABLE_NAME='findings' THEN
   SELECT case_id INTO target FROM public.scans WHERE id=NEW.scan_id;
 ELSIF TG_TABLE_NAME='investigations' THEN
   SELECT s.case_id INTO target FROM public.findings f JOIN public.scans s ON s.id=f.scan_id WHERE f.id=NEW.finding_id;
 ELSE target=NEW.case_id;
 END IF;
 UPDATE public.cases SET revision=revision+1 WHERE id=target;
 RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS sentinel_revision ON public.scans;
CREATE TRIGGER sentinel_revision AFTER INSERT ON public.scans FOR EACH ROW EXECUTE FUNCTION public.sentinel_case_revision();
DROP TRIGGER IF EXISTS sentinel_revision ON public.findings;
CREATE TRIGGER sentinel_revision AFTER INSERT OR UPDATE ON public.findings FOR EACH ROW EXECUTE FUNCTION public.sentinel_case_revision();
DROP TRIGGER IF EXISTS sentinel_revision ON public.questions;
CREATE TRIGGER sentinel_revision AFTER INSERT ON public.questions FOR EACH ROW EXECUTE FUNCTION public.sentinel_case_revision();
DROP TRIGGER IF EXISTS sentinel_revision ON public.investigations;
CREATE TRIGGER sentinel_revision AFTER INSERT ON public.investigations FOR EACH ROW EXECUTE FUNCTION public.sentinel_case_revision();
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC;
