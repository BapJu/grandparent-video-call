-- Visio-TV: photo frame storage. Run once in the Supabase SQL Editor,
-- after setup.sql (it reuses public.is_family_member()).
--
-- The Pi caches these photos locally and only downloads what it doesn't
-- already have, so nothing is re-fetched over 4G on every slideshow.

-- Private bucket: objects are only reachable with a family member's JWT.
insert into storage.buckets (id, name, public)
values ('photos', 'photos', false)
on conflict (id) do nothing;

-- Family members can browse, add and remove photos. The Pi's device account
-- is in family_members too, which is how it lists and downloads them.
create policy "family can view photos"
on storage.objects for select
to authenticated
using ( bucket_id = 'photos' and (select public.is_family_member()) );

create policy "family can upload photos"
on storage.objects for insert
to authenticated
with check ( bucket_id = 'photos' and (select public.is_family_member()) );

create policy "family can delete photos"
on storage.objects for delete
to authenticated
using ( bucket_id = 'photos' and (select public.is_family_member()) );
