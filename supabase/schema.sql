-- GridBot Signal v8.5 — jalankan SEKALI dalam Supabase SQL Editor.
-- Mencipta 5 jadual + polisi RLS guna-perseorangan (kunci anon boleh baca/tulis).
-- AMARAN: jika dashboard dikongsi awam, ketatkan dengan Supabase Auth (Fasa 2).

create table if not exists signals(
  id text primary key, ts timestamptz, sym text, tf text, dir text, grade text,
  prob numeric, entry numeric, sl numeric, tp1 numeric, tp2 numeric, rr1 numeric,
  regime text, session text, fgi numeric, created_at timestamptz default now());

create table if not exists journal_trades(
  id text primary key, row jsonb, updated_at timestamptz default now());

create table if not exists paper_trades(
  id text primary key, sym text, dir text, entry numeric, sl numeric,
  notion numeric, risk_usd numeric, fee_usd numeric, status text default 'OPEN',
  exit_gross_r numeric, net_r numeric,
  opened_at timestamptz, closed_at timestamptz);

create table if not exists tune_runs(
  id uuid primary key default gen_random_uuid(), ts timestamptz, mode text,
  seed int, budget int, scope int, hypo text, verdict text,
  winner jsonb, winner_hold numeric, trials jsonb, baseline jsonb,
  created_at timestamptz default now());

create table if not exists backtest_runs(
  id uuid primary key default gen_random_uuid(), ts timestamptz, label text,
  n int, wr numeric, exp_r numeric, pf numeric, detail jsonb,
  created_at timestamptz default now());

alter table signals enable row level security;
alter table journal_trades enable row level security;
alter table paper_trades enable row level security;
alter table tune_runs enable row level security;
alter table backtest_runs enable row level security;

create policy signals_anon on signals for all to anon using (true) with check (true);
create policy jtrades_anon on journal_trades for all to anon using (true) with check (true);
create policy paper_anon on paper_trades for all to anon using (true) with check (true);
create policy tune_anon on tune_runs for all to anon using (true) with check (true);
create policy bt_anon on backtest_runs for all to anon using (true) with check (true);

create index if not exists idx_signals_ts on signals(ts desc);
create index if not exists idx_paper_status on paper_trades(status);
