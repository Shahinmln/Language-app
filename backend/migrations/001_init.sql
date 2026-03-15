-- TaleTalk – canonical schema for public.stories (aligned with backend insert payload)
-- Run in Supabase SQL editor. Use "Create migration" or run manually.

create extension if not exists "uuid-ossp";

-- Required for stories.user_id FK (Supabase standard)
create table if not exists public.profiles (
  id uuid references auth.users(id) on delete cascade primary key,
  display_name text,
  native_language text,
  learning_languages text[],
  about text,
  plan text not null default 'free' check (plan in ('free', 'monthly', 'annual')),
  plan_renewal_date date,
  created_at timestamptz default now()
);

-- Safe column backfill for profiles
do $$
begin
  if not exists (select 1 from information_schema.columns where table_schema = 'public' and table_name = 'profiles' and column_name = 'native_language') then
    alter table public.profiles add column native_language text;
  end if;
  if not exists (select 1 from information_schema.columns where table_schema = 'public' and table_name = 'profiles' and column_name = 'learning_languages') then
    alter table public.profiles add column learning_languages text[];
  end if;
  if not exists (select 1 from information_schema.columns where table_schema = 'public' and table_name = 'profiles' and column_name = 'about') then
    alter table public.profiles add column about text;
  end if;
  if not exists (select 1 from information_schema.columns where table_schema = 'public' and table_name = 'profiles' and column_name = 'plan') then
    alter table public.profiles add column plan text not null default 'free';
  end if;
  if not exists (select 1 from information_schema.columns where table_schema = 'public' and table_name = 'profiles' and column_name = 'plan_renewal_date') then
    alter table public.profiles add column plan_renewal_date date;
  end if;
  if not exists (select 1 from information_schema.columns where table_schema = 'public' and table_name = 'profiles' and column_name = 'public_profile') then
    alter table public.profiles add column public_profile boolean default false;
  end if;
end $$;

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
  patterns jsonb,
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
  if not exists (select 1 from information_schema.columns where table_schema = 'public' and table_name = 'stories' and column_name = 'patterns') then
    alter table public.stories add column patterns jsonb;
  end if;
end $$;

-- ---------------------------------------------------------------------------
-- user_words: tracks per-user vocabulary status and encounters
-- ---------------------------------------------------------------------------
create table if not exists public.user_words (
  id uuid primary key default uuid_generate_v4(),
  user_id uuid references public.profiles(id) on delete cascade,
  word text not null,
  target_language text not null default 'en',
  status text not null default 'new' check (status in ('new', 'learning', 'reviewing', 'mastered')),
  times_encountered int default 0,
  times_clicked int default 0,
  last_encountered_date date,
  last_review_date date,
  next_review_date date,
  created_at timestamptz default now()
);

-- Safe column backfill for user_words
do $$
begin
  if not exists (select 1 from information_schema.columns where table_schema = 'public' and table_name = 'user_words' and column_name = 'times_clicked') then
    alter table public.user_words add column times_clicked int default 0;
  end if;
  if not exists (select 1 from information_schema.columns where table_schema = 'public' and table_name = 'user_words' and column_name = 'last_encountered_date') then
    alter table public.user_words add column last_encountered_date date;
  end if;
  if not exists (select 1 from information_schema.columns where table_schema = 'public' and table_name = 'user_words' and column_name = 'last_review_date') then
    alter table public.user_words add column last_review_date date;
  end if;
  if not exists (select 1 from information_schema.columns where table_schema = 'public' and table_name = 'user_words' and column_name = 'next_review_date') then
    alter table public.user_words add column next_review_date date;
  end if;
end $$;

-- ---------------------------------------------------------------------------
-- word_learning_history: detailed interaction log for words
-- ---------------------------------------------------------------------------
create table if not exists public.word_learning_history (
  id uuid primary key default uuid_generate_v4(),
  user_id uuid references public.profiles(id) on delete cascade,
  word text not null,
  target_language text not null default 'en',
  event_type text not null,
  context_data jsonb,
  created_at timestamptz default now()
);

-- ---------------------------------------------------------------------------
-- story_interactions: per-story engagement events (play, complete, like, quiz)
-- ---------------------------------------------------------------------------
create table if not exists public.story_interactions (
  id uuid primary key default uuid_generate_v4(),
  user_id uuid references public.profiles(id) on delete cascade,
  story_id uuid references public.stories(id) on delete cascade,
  action text not null,
  result jsonb,
  created_at timestamptz default now()
);

-- Safe column backfill for story_interactions.action (if table existed without it)
do $$
begin
  if not exists (select 1 from information_schema.columns where table_schema = 'public' and table_name = 'story_interactions' and column_name = 'action') then
    alter table public.story_interactions add column action text;
  end if;
end $$;

-- ---------------------------------------------------------------------------
-- daily_progress: lightweight daily aggregates per user
-- ---------------------------------------------------------------------------
create table if not exists public.daily_progress (
  id uuid primary key default uuid_generate_v4(),
  user_id uuid references public.profiles(id) on delete cascade,
  date date not null,
  stories_completed int default 0,
  created_at timestamptz default now(),
  unique (user_id, date)
);

-- ---------------------------------------------------------------------------
-- tests: store quiz/test results with per-question correctness
-- ---------------------------------------------------------------------------
create table if not exists public.tests (
  id uuid primary key default uuid_generate_v4(),
  user_id uuid references public.profiles(id) on delete cascade,
  story_id uuid references public.stories(id) on delete cascade,
  score numeric,
  max_score numeric,
  details jsonb,
  created_at timestamptz default now()
);

-- ---------------------------------------------------------------------------
-- analytics_events: anonymized/low-granularity events for product analytics
-- ---------------------------------------------------------------------------
create table if not exists public.analytics_events (
  id uuid primary key default uuid_generate_v4(),
  user_id uuid references public.profiles(id) on delete cascade,
  event_name text not null,
  story_id uuid references public.stories(id),
  story_duration_minutes int,
  quiz_type text,
  progress_percent numeric,
  metadata jsonb,
  created_at timestamptz default now()
);

-- Safe backfill for analytics_events if table already exists
do $$
begin
  if not exists (select 1 from information_schema.columns where table_schema = 'public' and table_name = 'analytics_events' and column_name = 'story_duration_minutes') then
    alter table public.analytics_events add column story_duration_minutes int;
  end if;
  if not exists (select 1 from information_schema.columns where table_schema = 'public' and table_name = 'analytics_events' and column_name = 'quiz_type') then
    alter table public.analytics_events add column quiz_type text;
  end if;
  if not exists (select 1 from information_schema.columns where table_schema = 'public' and table_name = 'analytics_events' and column_name = 'progress_percent') then
    alter table public.analytics_events add column progress_percent numeric;
  end if;
end $$;


