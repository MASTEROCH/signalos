-- SignalOS — схема для Supabase (Postgres). Вставь в Supabase → SQL Editor → Run.
create table if not exists users(
  id bigserial primary key,
  email text unique,
  pass_hash text, salt text,
  plan text default 'free',
  credits integer default 300,
  created double precision
);
create table if not exists sessions(
  token text primary key,
  user_id bigint references users(id) on delete cascade,
  created double precision
);
create table if not exists configs(
  user_id bigint primary key references users(id) on delete cascade,
  data jsonb
);
create table if not exists signals(
  id bigserial primary key,
  user_id bigint references users(id) on delete cascade,
  external_id text, source text, source_label text, project text,
  author text, text text, url text,
  temp text, strength integer, conf integer,
  why text, hl text, draft text, lang text,
  status text default 'queue',
  ts double precision, created double precision,
  unique(user_id, external_id)
);
create index if not exists idx_signals_user on signals(user_id, status);
