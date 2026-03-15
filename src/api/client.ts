/**
 * Single API client for TaleTalk backend.
 * Safe for Vercel serverless: no window or browser-only APIs.
 * Base URL from VITE_API_URL; if missing, fallback to localhost for local dev only.
 */

const DEFAULT_BASE = "http://localhost:8000";

function getBaseUrl(): string {
  const envBase = import.meta.env.VITE_API_URL;
  if (typeof envBase === "string" && envBase.trim() !== "") {
    const base = envBase.trim();
    if (/^https?:\/\//i.test(base)) {
      return base.replace(/\/+$/, "");
    }
    return base.startsWith("//") ? `https:${base}` : `https://${base}`;
  }
  return DEFAULT_BASE;
}

export async function request<T>(
  path: string,
  options?: RequestInit & { params?: Record<string, string | number | undefined> }
): Promise<T> {
  const base = getBaseUrl();
  const { params, ...init } = options ?? {};

  const isAbsolute = /^https?:\/\//i.test(path);
  const url = isAbsolute ? new URL(path) : new URL(path.startsWith("/") ? path : `/${path}`, base);
  if (params) {
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== "") url.searchParams.set(k, String(v));
    });
  }
  console.log("API Request:", url.toString());
  const res = await fetch(url.toString(), {
    ...init,
    headers: { "Content-Type": "application/json", ...init.headers },
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `HTTP ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export interface Story {
  id: string;
  title?: string | null;
  topic?: string | null;
  target_language?: string | null;
  cefr_level?: string | null;
  duration_minutes?: number | null;
  content?: string | null;
  audio_url?: string | null;
  transcript_json?: unknown;
  vocabulary?: unknown;
  visibility?: string | null;
  word_list?: string[] | null;
  target_words?: string[] | null;
  plays_count?: number | null;
  badge?: string;
  total_score?: number;
  recommendation_reason?: string;
  patterns?: {
    structure?: string;
    explanation?: string;
    examples?: string[];
  }[];
}

export interface GetStoriesParams {
  level?: string;
  topic?: string;
  language?: string;
  limit?: number;
}

export function getStories(params?: GetStoriesParams) {
  return request<{ stories: Story[] }>("/api/stories", {
    params: params as unknown as Record<string, string | number | undefined>,
  });
}

export function getStory(storyId: string) {
  return request<{ story: Story }>(`/api/stories/${storyId}`);
}

export function simplifyStory(storyId: string) {
  return request<{ story: Story }>(`/api/stories/${storyId}/simplify`, { method: "POST" });
}

export interface GenerateStoryParams {
  topic: string;
  duration: number;
  level: string;
  language?: string;
  user_id?: string;
}

export interface GenerateStoryBody {
  target_words?: string[] | null;
}

export function generateStory(params: GenerateStoryParams, body?: GenerateStoryBody | null) {
  const search = new URLSearchParams();
  search.set("topic", params.topic);
  search.set("duration", String(params.duration));
  search.set("level", params.level);
  if (params.language) search.set("language", params.language);
  if (params.user_id) search.set("user_id", params.user_id);
  // Only send body when we have at least one non-empty trimmed word; never send placeholders or blanks
  const words =
    body?.target_words?.filter((w): w is string => typeof w === "string" && w.trim() !== "").map((w) => w.trim()) ??
    [];
  const payload =
    words.length > 0 ? JSON.stringify({ target_words: words }) : undefined;
  return request<{ success: boolean; story_id: string; story: unknown; quiz: unknown }>(
    `/api/generate-story?${search}`,
    { method: "POST", body: payload }
  );
}

export function trackWord(params: {
  user_id: string;
  word: string;
  action: string;
  story_id?: string;
  target_language?: string;
}) {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== "") search.set(k, String(v));
  });
  return request<{ success: boolean }>(`/api/track-word?${search}`, { method: "POST" });
}

export function getUserWords(
  userId: string,
  params?: { status?: string; target_language?: string }
) {
  const search = new URLSearchParams();
  if (params?.status) search.set("status", params.status);
  if (params?.target_language) search.set("target_language", params.target_language);
  const q = search.toString();
  return request<{ words: unknown[] }>(`/api/user-words/${userId}${q ? `?${q}` : ""}`);
}

export interface WordBankItem {
  word: string;
  definition?: string;
  translation?: string;
  example?: string;
  pos?: string;
  status?: string;
}

export function getStoryWordBank(storyId: string, userId: string, targetLanguage?: string) {
  return request<{ words: WordBankItem[] }>(`/api/stories/${storyId}/word-bank`, {
    params: {
      user_id: userId,
      target_language: targetLanguage,
    },
  });
}

export function trackInteraction(params: {
  user_id: string;
  story_id: string;
  action: string;
  result?: unknown;
}) {
  const { result, ...rest } = params;
  const search = new URLSearchParams();
  Object.entries(rest).forEach(([k, v]) => { if (v != null && v !== "") search.set(k, String(v)); });
  return request<{ success: boolean }>(`/api/track-interaction?${search}`, { method: "POST" });
}

export interface ExploreProParams {
  user_id: string;
  limit?: number;
  min_score?: number;
  language?: string;
}

export function explorePro(params: ExploreProParams) {
  return request<{ stories: Story[] }>("/api/explore/pro", {
    params: params as unknown as Record<string, string | number | undefined>,
  });
}
