-- Publication catalog. Git and GitHub Releases stay the system of record
-- for artifacts; these tables are the mutable catalog and workflow state.
-- Design only: not applied to any project yet. Apply via the Supabase CLI
-- from CI (`supabase --workdir infra db push`), never from a laptop.

create type publication_status as enum
  ('draft', 'candidate', 'validated', 'approved', 'tagged', 'published', 'corrected');

create table publications (
  id               uuid primary key default gen_random_uuid(),
  kind             text not null check (kind in ('paper', 'dataset')),
  slug             text not null unique check (slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'),
  title            text not null,
  status           publication_status not null default 'draft',
  current_version  text,
  git_repo         text not null default 'humanaios-ui/research',
  entity_version   bigint not null default 1,
  updated_at       timestamptz not null default now()
);

create table publication_versions (
  id                     uuid primary key default gen_random_uuid(),
  publication_id         uuid not null references publications(id),
  version                text not null check (version ~ '^\d+\.\d+\.\d+$'),
  git_commit             text not null check (git_commit ~ '^[0-9a-f]{40}$'),
  release_tag            text not null unique,
  manifest_sha256        text not null check (manifest_sha256 ~ '^[0-9a-f]{64}$'),
  z2_ratification_hash   text not null check (z2_ratification_hash ~ '^[0-9a-f]{64}$'),
  release_url            text,
  corrects_version_id    uuid references publication_versions(id),
  released_at            timestamptz,
  unique (publication_id, version)
);

create table datasets (
  id              uuid primary key default gen_random_uuid(),
  registry_id     text not null unique,        -- registry/datasets.json "id"
  slug            text not null,
  method_version  text not null,
  time_window     text,
  path            text not null,
  sha256          text not null check (sha256 ~ '^[0-9a-f]{64}$'),
  license         text not null,
  lifecycle       text not null check (lifecycle in ('draft', 'active', 'frozen', 'deprecated', 'corrected'))
);

create table publication_datasets (
  publication_id  uuid not null references publications(id),
  dataset_id      uuid not null references datasets(id),
  primary key (publication_id, dataset_id)
);

create table release_artifacts (
  id                      uuid primary key default gen_random_uuid(),
  publication_version_id  uuid not null references publication_versions(id),
  name                    text not null,
  media_type              text,
  sha256                  text not null check (sha256 ~ '^[0-9a-f]{64}$'),
  bytes                   bigint not null check (bytes >= 0),
  release_url             text,
  unique (publication_version_id, name)
);

-- Sanitized only: no subscription ids or raw resource ids.
create table azure_resources (
  id                 uuid primary key default gen_random_uuid(),
  resource_name      text not null,
  resource_type      text not null,
  resource_group     text not null,
  region             text,
  azure_id_complete  boolean not null,
  azure_id_sha256    text check (azure_id_sha256 ~ '^[0-9a-f]{64}$'),
  last_observed_at   timestamptz not null,
  unique (resource_type, resource_group, resource_name)
);

-- Transactional outbox: written in the same transaction as the change it
-- announces; a worker delivers it (Gmail draft, optional Cosmos projection).
create table outbox_events (
  event_id        uuid primary key default gen_random_uuid(),
  event_type      text not null,               -- e.g. publication.published
  entity_id       uuid not null,
  entity_version  bigint not null,
  source_commit   text,
  payload         jsonb not null default '{}',
  occurred_at     timestamptz not null default now(),
  delivered_at    timestamptz,
  attempts        int not null default 0,
  last_error      text
);
create index outbox_undelivered on outbox_events (occurred_at) where delivered_at is null;

create table notifications (
  id                      uuid primary key default gen_random_uuid(),
  publication_version_id  uuid not null references publication_versions(id),
  channel                 text not null check (channel in ('gmail')),
  state                   text not null check (state in ('drafted', 'sent', 'failed')),
  external_id             text,                -- Gmail draft or message id
  sent_at                 timestamptz
);

-- Compare-and-set: every update must set entity_version to exactly the
-- version it read plus one. Omitting the column (new = old) is rejected,
-- like a stale write, so a writer cannot skip the check by accident.
create function check_entity_version() returns trigger language plpgsql as $$
begin
  if new.entity_version <> old.entity_version + 1 then
    raise exception 'write to % must set entity_version = % (read-version + 1), sent %',
      old.id, old.entity_version + 1, new.entity_version
      using errcode = '40001';
  end if;
  new.updated_at := now();
  return new;
end $$;
create trigger publications_version before update on publications
  for each row execute function check_entity_version();

-- Published versions are immutable; a correction is a new row.
create function forbid_published_version_edit() returns trigger language plpgsql as $$
begin
  if old.released_at is not null then
    raise exception 'release % is published; add a correcting version instead', old.release_tag;
  end if;
  return case when tg_op = 'DELETE' then old else new end;
end $$;
create trigger publication_versions_immutable before update or delete on publication_versions
  for each row execute function forbid_published_version_edit();

-- Artifacts of a published version are frozen with it: no insert, update
-- or delete, and no moving an artifact into or out of a published version.
create function forbid_released_artifact_edit() returns trigger language plpgsql as $$
begin
  -- Lock the parent version row(s) first, in id order, so a concurrent
  -- release (UPDATE of released_at) cannot commit between this check and
  -- the artifact write. FOR SHARE still lets artifacts of an unreleased
  -- version be added in parallel; the checks below then run as new
  -- statements and see a release that committed while we waited.
  perform 1 from publication_versions v
   where v.id in (case when tg_op <> 'INSERT' then old.publication_version_id end,
                  case when tg_op <> 'DELETE' then new.publication_version_id end)
   order by v.id
   for share;
  if (tg_op in ('UPDATE', 'DELETE') and exists (
        select 1 from publication_versions v
        where v.id = old.publication_version_id and v.released_at is not null))
     or (tg_op in ('INSERT', 'UPDATE') and exists (
        select 1 from publication_versions v
        where v.id = new.publication_version_id and v.released_at is not null)) then
    raise exception 'artifact belongs to a published version; add a correcting version instead';
  end if;
  return case when tg_op = 'DELETE' then old else new end;
end $$;
create trigger release_artifacts_immutable before insert or update or delete on release_artifacts
  for each row execute function forbid_released_artifact_edit();

-- Row level security: the public may read published catalog rows only.
-- Writes go through the service role from CI / workers, which bypasses RLS.
alter table publications          enable row level security;
alter table publication_versions  enable row level security;
alter table datasets              enable row level security;
alter table publication_datasets  enable row level security;
alter table release_artifacts     enable row level security;
alter table azure_resources       enable row level security;
alter table outbox_events         enable row level security;
alter table notifications         enable row level security;

create policy public_read_published on publications for select to anon, authenticated
  using (status in ('published', 'corrected'));
create policy public_read_released on publication_versions for select to anon, authenticated
  using (released_at is not null);
create policy public_read_frozen on datasets for select to anon, authenticated
  using (lifecycle in ('frozen', 'corrected'));
create policy public_read_links on publication_datasets for select to anon, authenticated
  using (exists (select 1 from publications p where p.id = publication_id
                 and p.status in ('published', 'corrected')));
create policy public_read_artifacts on release_artifacts for select to anon, authenticated
  using (exists (select 1 from publication_versions v where v.id = publication_version_id
                 and v.released_at is not null));
-- azure_resources, outbox_events, notifications: no public policy (internal).
