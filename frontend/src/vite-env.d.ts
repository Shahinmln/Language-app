/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Backend API base URL (e.g. https://your-api.fly.dev). Required in production (e.g. Vercel). */
  readonly VITE_API_URL?: string;
  /** Supabase project URL. Required for auth. */
  readonly VITE_SUPABASE_URL?: string;
  /** Supabase anon/public key. Required for auth. */
  readonly VITE_SUPABASE_ANON_KEY?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
