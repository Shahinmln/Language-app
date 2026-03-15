import { useEffect, useRef, useState } from "react";
import { useAuth } from "../auth/AuthContext";
import { request } from "../api/client";

interface ReviewWord {
  id?: string;
  word: string;
  target_language?: string;
  status?: string;
}

interface PendingAnswer {
  word: string;
  correct: boolean;
}

export default function ReviewPage() {
  const { user } = useAuth();
  const [words, setWords] = useState<ReviewWord[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [index, setIndex] = useState(0);
  const [answers, setAnswers] = useState<PendingAnswer[]>([]);
  const [sessionDone, setSessionDone] = useState(false);
  const lastSubmitRef = useRef<(() => Promise<void>) | null>(null);

  useEffect(() => {
    if (!user) return;
    setLoading(true);
    setError(null);
    request<{ words: ReviewWord[] }>(`/api/review-words?user_id=${encodeURIComponent(user.id)}&limit=10`)
      .then((res) => {
        setWords(res.words ?? []);
        setIndex(0);
        setAnswers([]);
        setSessionDone(false);
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load review words"))
      .finally(() => setLoading(false));
  }, [user?.id]);

  const current = words[index];

  const recordAnswer = async (correct: boolean) => {
    if (!current || !user) return;
    const nextAnswers = [...answers, { word: current.word, correct }];
    const nextIndex = index + 1;
    setAnswers(nextAnswers);

    if (nextIndex < words.length) {
      setIndex(nextIndex);
      return;
    }

    // Session finished: send results to backend
    const submit = async () => {
      setLoading(true);
      try {
        await request<{ success: boolean }>("/api/review-words", {
          method: "POST",
          body: JSON.stringify({
            user_id: user.id,
            items: nextAnswers,
          }),
        });
        setSessionDone(true);
      } catch (e) {
        setError(
          e instanceof Error
            ? e.message
            : "Failed to save review results. We’re saving your progress, try again in a moment."
        );
      } finally {
        setLoading(false);
      }
    };

    lastSubmitRef.current = submit;
    await submit();
  };

  if (!user) {
    return <p className="page-subtitle">Sign in to review your words.</p>;
  }

  return (
    <div className="page-card">
      <h1 className="page-title">Quick review</h1>
      <p className="page-subtitle">
        We&apos;ll show you a few words. In your head, recall the meaning and try to use it in a sentence, then mark whether you remembered it.
      </p>
      {loading && <p className="page-subtitle">Loading…</p>}
      {error && (
        <p style={{ color: "var(--error)" }}>
          {error}{" "}
          {lastSubmitRef.current && (
            <button
              type="button"
              className="btn btn-small btn-outline"
              style={{ marginLeft: 8 }}
              onClick={() => {
                if (lastSubmitRef.current) {
                  lastSubmitRef.current();
                }
              }}
            >
              Retry save
            </button>
          )}
        </p>
      )}

      {!loading && !sessionDone && current && (
        <div style={{ marginTop: 16 }}>
          <div className="card" style={{ marginBottom: 16 }}>
            <div className="card-title" style={{ fontSize: 20 }}>
              {current.word}
            </div>
            <p className="page-subtitle" style={{ marginTop: 8 }}>
              Think of the meaning and say a sentence with this word in your target language.
            </p>
            <p style={{ fontSize: 13, color: "var(--text-secondary)" }}>
              Card {index + 1} of {words.length}
            </p>
          </div>
          <div className="chips-row">
            <button
              type="button"
              className="btn btn-primary btn-pill"
              onClick={() => recordAnswer(true)}
              disabled={loading}
            >
              I remembered it
            </button>
            <button
              type="button"
              className="btn btn-outline btn-pill"
              onClick={() => recordAnswer(false)}
              disabled={loading}
            >
              I forgot / not sure
            </button>
          </div>
        </div>
      )}

      {!loading && !error && words.length === 0 && !sessionDone && (
        <p className="page-subtitle">No words are due for review right now. Try again later after reading more stories.</p>
      )}

      {sessionDone && (
        <p className="page-subtitle">
          Review saved. You can revisit this page later today for more practice, or continue exploring new stories.
        </p>
      )}
    </div>
  );
}

