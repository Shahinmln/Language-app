import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { request, type Story } from "../api/client";

export default function HistoryPage() {
  const { user } = useAuth();
  const [stories, setStories] = useState<Story[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!user) return;
    setLoading(true);
    setError(null);
    request<{ stories: Story[] }>(`/api/my-stories?user_id=${encodeURIComponent(user.id)}`)
      .then((res) => setStories(res.stories ?? []))
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load history"))
      .finally(() => setLoading(false));
  }, [user?.id]);

  if (!user) {
    return <p className="page-subtitle">Sign in to view your history.</p>;
  }

  return (
    <div className="page-card">
      <h1 className="page-title">Your story history</h1>
      <p className="page-subtitle">All stories you have generated with TaleTalk.</p>
      {loading && <p className="page-subtitle">Loading…</p>}
      {error && <p style={{ color: "var(--error)" }}>{error}</p>}
      {!loading && !error && stories.length === 0 && (
        <p className="page-subtitle">You haven&apos;t generated any stories yet.</p>
      )}
      {!loading && stories.length > 0 && (
        <ul className="story-list">
          {stories.map((s) => (
            <li key={s.id}>
              <Link to={`/story/${s.id}`} state={{ story: s }} className="card">
                <strong className="card-title">{s.title ?? "Untitled"}</strong>
                <span className="card-meta">
                  {s.cefr_level} · {s.duration_minutes ?? 0} min · {s.topic}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

