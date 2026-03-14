import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { request } from "../api/client";

interface TestRow {
  id: string;
  story_id?: string;
  score?: number;
  max_score?: number;
  details?: unknown;
  created_at?: string;
}

export default function TestsPage() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [tests, setTests] = useState<TestRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [practicingId, setPracticingId] = useState<string | null>(null);

  useEffect(() => {
    if (!user) return;
    setLoading(true);
    setError(null);
    request<{ tests: TestRow[] }>(`/api/tests/${encodeURIComponent(user.id)}`)
      .then((res) => setTests(res.tests ?? []))
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load tests"))
      .finally(() => setLoading(false));
  }, [user?.id]);

  if (!user) {
    return <p className="page-subtitle">Sign in to view your test history.</p>;
  }

  return (
    <div className="page-card">
      <h1 className="page-title">Your tests</h1>
      <p className="page-subtitle">
        Review your test scores and see which questions were correct or needed more work.
      </p>
      {loading && <p className="page-subtitle">Loading…</p>}
      {error && <p style={{ color: "var(--error)" }}>{error}</p>}
      {!loading && !error && tests.length === 0 && (
        <p className="page-subtitle">You haven&apos;t completed any tests yet.</p>
      )}
      {!loading && tests.length > 0 && (
        <ul className="vocab-list">
          {tests.map((t) => {
            const score = t.score ?? 0;
            const max = t.max_score ?? 0;
            const ratio = max > 0 ? Math.round((score / max) * 100) : 0;
            let details: any[] = [];
            if (Array.isArray(t.details)) {
              details = t.details as any[];
            } else if (t.details && typeof t.details === "object" && Array.isArray((t.details as any).questions)) {
              details = (t.details as any).questions;
            }
            const hasDetails = details.length > 0;
            const wrongCount = hasDetails ? details.filter((d) => !d.correct).length : 0;
            return (
              <li key={t.id} className="vocab-item" style={{ flexDirection: "column", alignItems: "flex-start" }}>
                <div>
                  <strong>Story {t.story_id ?? "–"}</strong>{" "}
                  <span style={{ color: "var(--text-secondary)", fontSize: 13 }}>
                    {t.created_at ? new Date(t.created_at).toLocaleString() : ""}
                  </span>
                </div>
                <div style={{ fontSize: 14, marginTop: 4 }}>
                  Score:{" "}
                  <span style={{ color: ratio >= 70 ? "var(--success)" : "var(--error)" }}>
                    {score}/{max} ({ratio}%)
                  </span>
                </div>
                {hasDetails && (
                  <div style={{ marginTop: 8, fontSize: 13 }}>
                    {details.map((d, i) => {
                      const correct = !!d.correct;
                      const label = d.word || d.question || `Item ${i + 1}`;
                      return (
                        <div key={i} style={{ marginBottom: 4 }}>
                          <span style={{ color: correct ? "var(--success)" : "var(--error)" }}>
                            {correct ? "✓" : "✗"} {label}
                          </span>
                        </div>
                      );
                    })}
                  </div>
                )}
                {hasDetails && wrongCount > 0 && (
                  <div style={{ marginTop: 8 }}>
                    <button
                      type="button"
                      className="btn btn-small btn-outline"
                      disabled={practicingId === t.id}
                      onClick={async () => {
                        if (!user) return;
                        setPracticingId(t.id);
                        try {
                          await request<{ success: boolean; words: string[] }>(`/api/tests/${t.id}/practice-again`, {
                            method: "POST",
                            body: JSON.stringify({
                              user_id: user.id,
                              // target_language can be inferred server-side or extended later
                            }),
                          });
                          // After pushing words into SRS, jump straight into a review session.
                          navigate("/review");
                        } catch (e) {
                          // best-effort: ignore errors, user can still use normal Review
                        } finally {
                          setPracticingId(null);
                        }
                      }}
                    >
                      {practicingId === t.id ? "Preparing review…" : "Practice these again"}
                    </button>
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

