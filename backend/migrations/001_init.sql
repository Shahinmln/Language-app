-- StoryPod AI – canonical schema for public.stories (aligned with backend insert payload)
-- Run in Supabase SQL editor. Use "Create migration" or run manually.

create extension if not exists "uuid-ossp";

-- Required for stories.user_id FK (Supabase standard)
create table if not exists public.profiles (
  id uuid references auth.users(id) on delete cascade primary key,
  display_name text,
  created_at timestamptz default now()
);

-- Canonical stories table: every column the backend may insert or read
create table if not exists public.stories (
  id uuid primary key default uuid_generate_v4(),
  user_id uuid references public.profiles(id),
  title text not null,
  topic text not null,
  target_language text not null,
  cefr_level text,
  duration_minutes int,
  content text,
  audio_url text,
  transcript_json jsonb,
  vocabulary jsonb,
  plays_count int default 0,
  likes_count int default 0,
  completion_rate numeric default 0.50,
  word_list text[],
  target_words text[],
  visibility text default 'public' check (visibility in ('public', 'anonymous', 'private')),
  is_featured boolean default false,
  created_at timestamptz default now()
);

-- Optional: add columns if table already existed without them (safe to run multiple times)
do $$
begin
  if not exists (select 1 from information_schema.columns where table_schema = 'public' and table_name = 'stories' and column_name = 'word_list') then
    alter table public.stories add column word_list text[];
  end if;
  if not exists (select 1 from information_schema.columns where table_schema = 'public' and table_name = 'stories' and column_name = 'target_words') then
    alter table public.stories add column target_words text[];
  end if;
end $$;
