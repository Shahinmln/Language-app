/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Backend API base URL (e.g. https://your-api.fly.dev). Required in production (e.g. Vercel). */
  readonly VITE_API_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
