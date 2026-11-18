-- VEXARO CLIPS starter schema. Apply only to a dedicated VEXARO project.
create extension if not exists pgcrypto;
create table if not exists public.video_jobs (
 id uuid primary key default gen_random_uuid(),
 user_id uuid not null references auth.users(id) on delete cascade,
 source_type text not null check (source_type in ('upload','youtube')),
 source_path text,
 source_url text,
 original_filename text,
 file_size_bytes bigint check (file_size_bytes is null or file_size_bytes <= 2147483648),
 category text not null default 'Other',
 requested_clip_count integer not null default 10 check (requested_clip_count between 1 and 50),
 aspect_ratio text not null default '9:16' check (aspect_ratio in ('9:16','1:1','16:9')),
 caption_language text not null default 'Auto detect',
 status text not null default 'queued' check (status in ('queued','uploading','processing','completed','failed')),
 error_message text,
 created_at timestamptz not null default now(),
 updated_at timestamptz not null default now(),
 constraint source_present check ((source_type='upload' and source_path is not null) or (source_type='youtube' and source_url is not null))
);
create table if not exists public.generated_clips (
 id uuid primary key default gen_random_uuid(),
 job_id uuid not null references public.video_jobs(id) on delete cascade,
 user_id uuid not null references auth.users(id) on delete cascade,
 storage_path text not null,
 title text,
 start_seconds numeric,
 end_seconds numeric,
 duration_seconds numeric,
 created_at timestamptz not null default now()
);
alter table public.video_jobs enable row level security;
alter table public.generated_clips enable row level security;
create policy "Users read own jobs" on public.video_jobs for select to authenticated using ((select auth.uid())=user_id);
create policy "Users create own jobs" on public.video_jobs for insert to authenticated with check ((select auth.uid())=user_id);
create policy "Users update own jobs" on public.video_jobs for update to authenticated using ((select auth.uid())=user_id) with check ((select auth.uid())=user_id);
create policy "Users delete own jobs" on public.video_jobs for delete to authenticated using ((select auth.uid())=user_id);
create policy "Users read own clips" on public.generated_clips for select to authenticated using ((select auth.uid())=user_id);
create policy "Users add own clips" on public.generated_clips for insert to authenticated with check ((select auth.uid())=user_id and exists(select 1 from public.video_jobs j where j.id=job_id and j.user_id=(select auth.uid())));
create policy "Users delete own clips" on public.generated_clips for delete to authenticated using ((select auth.uid())=user_id);
-- Create private buckets in Storage dashboard: source-videos (2GB limit), generated-clips.
-- Large uploads should use TUS/resumable uploads. Add storage.objects RLS policies before enabling uploads.