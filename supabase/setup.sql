-- Visio-TV: family allowlist + Realtime Authorization for the private
-- 'visio-tv-calls' channel. Run once in the Supabase SQL Editor.
--
-- After running this, also (in the dashboard):
--   1. Insert family emails (lowercase) + the Pi device account email into
--      public.family_members.
--   2. Create the auth users (email + password, "Auto Confirm User" on).
--   3. Project Settings -> Realtime -> disable "Allow public access"
--      (closes the old public-channel path; do this only when the updated
--      Pi listener is ready to deploy).

-- ---------------------------------------------------------------------------
-- Family allowlist
-- ---------------------------------------------------------------------------
create table public.family_members (
  id uuid primary key default gen_random_uuid(),
  email text not null unique check (email = lower(email)),
  display_name text,
  created_at timestamptz not null default now()
);

alter table public.family_members enable row level security;

-- ---------------------------------------------------------------------------
-- Membership check used by all policies. SECURITY DEFINER so the Realtime
-- authorization check doesn't depend on grants/RLS of the querying role.
-- ---------------------------------------------------------------------------
create or replace function public.is_family_member()
returns boolean
language sql stable security definer
set search_path = public
as $$
  select exists (
    select 1 from public.family_members
    where email = lower(coalesce(auth.jwt() ->> 'email', ''))
  );
$$;

revoke all on function public.is_family_member() from public;
grant execute on function public.is_family_member() to authenticated;

-- Members can read the allowlist (used by the web app's membership gate).
-- No insert/update/delete policies: the list is managed from the dashboard.
create policy "family members can read allowlist"
on public.family_members for select
to authenticated
using ( (select public.is_family_member()) );

-- ---------------------------------------------------------------------------
-- Realtime Authorization: private channel 'visio-tv-calls'
-- (broadcast for start_call/end_call, presence for the Pi status)
-- ---------------------------------------------------------------------------
create policy "family can receive visio-tv-calls"
on realtime.messages for select
to authenticated
using (
  realtime.topic() = 'visio-tv-calls'
  and realtime.messages.extension in ('broadcast', 'presence')
  and (select public.is_family_member())
);

create policy "family can send visio-tv-calls"
on realtime.messages for insert
to authenticated
with check (
  realtime.topic() = 'visio-tv-calls'
  and realtime.messages.extension in ('broadcast', 'presence')
  and (select public.is_family_member())
);
