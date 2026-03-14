import { useEffect, useState } from "react";
import { getUserWords } from "../api/client";

import { useAuth } from "../auth/AuthContext";

interface UserWord {
  id?: string;
  word?: string;
  target_language?: string;
  status?: string;
  times_encountered?: number;
  created_at?: string;
  [key: string]: unknown;
}

export default function Vocabulary() {
  const { user } = useAuth();
  const [words, setWords] = useState<UserWord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState("");

  useEffect(() => {
    if (!user) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    getUserWords(user.id, statusFilter ? { status: statusFilter } : undefined)
      .then((res) => { if (!cancelled) setWords((res.words ?? []) as UserWord[]); })
      .catch((e) => { if (!cancelled) setError(e instanceof Error ? e.message : "Failed to load"); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [statusFilter, user?.id]);

  return (
    <div className="page-card">
      <h1 className="page-title">My Vocabulary</h1>
      <p className="page-subtitle">User: {user?.email ?? "Guest"}</p>
      <select
        value={statusFilter}
        onChange={(e) => setStatusFilter(e.target.value)}
        className="field-select"
        style={{ maxWidth: 200, marginBottom: 24 }}
      >
        <option value="">All</option>
        <option value="new">New</option>
        <option value="learning">Learning</option>
        <option value="reviewing">Reviewing</option>
        <option value="mastered">Mastered</option>
      </select>
      {loading && <p className="page-subtitle">Loading…</p>}
      {error && <p style={{ color: "var(--error)" }}>{error}</p>}
      {!loading && !error && words.length === 0 && <p className="page-subtitle">No words yet. Click words in a story to track them.</p>}
      {!loading && words.length > 0 && (
        <ul className="vocab-list">
          {words.map((w, i) => (
            <li key={w.id ?? i} className="vocab-item">
              <strong>{w.word}</strong>
              <span>{w.status}</span>
              {w.times_encountered != null && <span>· {w.times_encountered} seen</span>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
