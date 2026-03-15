import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getStories, explorePro, type Story } from "../api/client";

export default function Explore() {
  console.log("Explore page mounted");
  const [stories, setStories] = useState<Story[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [userId, setUserId] = useState("");
  const [level, setLevel] = useState("");
  const [language, setLanguage] = useState("en");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    const fetchStories = async () => {
      console.log("Fetching stories...");
      try {
        if (userId.trim()) {
          const res = await explorePro({
            user_id: userId.trim(),
            limit: 20,
            language: language || undefined,
          });
          const list = res.stories ?? [];
          if (!cancelled) {
            if (list.length > 0) setStories(list);
            else {
              const fallback = await getStories({ level: level || undefined, language: language || undefined });
              if (!cancelled) setStories(fallback.stories ?? []);
            }
          }
        } else {
          const res = await getStories({ level: level || undefined, language: language || undefined });
          if (!cancelled) setStories(res.stories ?? []);
        }
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "Failed to load");
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    fetchStories();
    return () => { cancelled = true; };
  }, [userId, level, language]);

  return (
    <div className="page-card">
      <h1 className="page-title">Explore Stories</h1>
      <div className="form-row-inline">
        <input
          type="text"
          placeholder="User ID (optional, for personalized)"
          value={userId}
          onChange={(e) => setUserId(e.target.value)}
          className="field-input"
        />
        <select
          value={language}
          onChange={(e) => setLanguage(e.target.value)}
          className="field-select"
        >
          <option value="en">English</option>
          <option value="es">Spanish</option>
          <option value="ko">Korean</option>
          <option value="tr">Turkish</option>
          <option value="ar">Arabic</option>
          <option value="zh">Chinese</option>
        </select>
        <select
          value={level}
          onChange={(e) => setLevel(e.target.value)}
          className="field-select"
        >
          <option value="">All levels</option>
          <option value="A1">A1</option>
          <option value="A2">A2</option>
          <option value="B1">B1</option>
          <option value="B2">B2</option>
          <option value="C1">C1</option>
          <option value="C2">C2</option>
        </select>
      </div>
      <Link to="/generate" className="btn btn-primary btn-pill" style={{ marginBottom: 24, display: "inline-flex" }}>
        Generate a story
      </Link>
      {loading && <p className="page-subtitle">Loading…</p>}
      {error && <p style={{ color: "var(--error)" }}>{error}</p>}
      {!loading && !error && stories.length === 0 && <p className="page-subtitle">No stories yet. Generate one to get started.</p>}
      {!loading && stories.length > 0 && (
        <ul className="story-list">
          {stories.map((s) => (
            <li key={s.id}>
              <Link to={`/story/${s.id}`} state={{ story: s }} className="card">
                <strong className="card-title">{s.title ?? "Untitled"}</strong>
                <span className="card-meta">
                  {s.cefr_level} · {s.duration_minutes ?? 0} min · {s.topic}
                </span>
                {(s.badge || s.total_score != null || s.recommendation_reason) && (
                  <span className="card-badge">
                    {s.badge || "✨ Recommended"}
                  </span>
                )}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
