import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { generateStory } from "../api/client";
import { useAuth } from "../auth/AuthContext";

const LEVELS = ["A1", "A2", "B1", "B2", "C1", "C2"] as const;
const LANGUAGES = ["en", "es", "ko", "tr", "ar", "zh"] as const;
const DURATION_MIN = 1;
const DURATION_MAX = 30;

export default function GenerateStory() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const [topic, setTopic] = useState("");
  const [duration, setDuration] = useState(5);
  const [level, setLevel] = useState("A1");
  const [language, setLanguage] = useState("en");
  const [targetWordsText, setTargetWordsText] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fieldError, setFieldError] = useState<string | null>(null);
  const lastActionRef = useRef<(() => Promise<void>) | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setFieldError(null);

    if (!user) {
      setFieldError("Please sign in to generate stories.");
      return;
    }

    const topicTrimmed = topic.trim();
    if (!topicTrimmed) {
      setFieldError("Topic is required.");
      return;
    }
    const durationNum = Number(duration);
    if (!Number.isInteger(durationNum) || durationNum < DURATION_MIN || durationNum > DURATION_MAX) {
      setFieldError(`Duration must be between ${DURATION_MIN} and ${DURATION_MAX} minutes.`);
      return;
    }
    if (!LEVELS.includes(level as (typeof LEVELS)[number])) {
      setFieldError("Please select a valid level.");
      return;
    }
    if (!LANGUAGES.includes(language as (typeof LANGUAGES)[number])) {
      setFieldError("Please select a valid language.");
      return;
    }

    const run = async () => {
      setLoading(true);
      try {
        const target_words = targetWordsText
          .trim()
          .split(/\s*,\s*/)
          .map((w) => w.trim())
          .filter((w) => w.length > 0);
        const res = await generateStory(
          { topic: topicTrimmed, duration: durationNum, level, language, user_id: user.id },
          target_words.length > 0 ? { target_words } : undefined
        );
        if (res.success && res.story_id) {
          navigate(`/story/${res.story_id}`, { state: { story: res.story, storyId: res.story_id } });
        } else {
          setError("Generation did not return a story ID.");
        }
      } catch (e) {
        setError(
          e instanceof Error
            ? e.message
            : "Generation failed. We’re saving your progress, try again in a moment."
        );
      } finally {
        setLoading(false);
      }
    };

    lastActionRef.current = run;
    await run();
  };

  return (
    <div className="page-card">
      <h1 className="page-title">Generate a Story</h1>
      <form onSubmit={handleSubmit} className="form" style={{ maxWidth: 400 }}>
        <label className="field">
          <span className="field-label">Topic</span>
          <input
            required
            value={topic}
            onChange={(e) => setTopic(e.target.value)}
            placeholder="e.g. travel, food"
            disabled={loading}
            className="field-input"
          />
        </label>
        <label className="field">
          <span className="field-label">Duration (minutes)</span>
          <input
            type="number"
            min={DURATION_MIN}
            max={DURATION_MAX}
            value={duration}
            onChange={(e) => setDuration(Number(e.target.value))}
            disabled={loading}
            className="field-input"
          />
          <span className="field-help">Between {DURATION_MIN} and {DURATION_MAX} minutes</span>
        </label>
        <label className="field">
          <span className="field-label">Level</span>
          <select
            value={level}
            onChange={(e) => setLevel(e.target.value)}
            disabled={loading}
            className="field-select"
          >
            <option value="A1">A1</option>
            <option value="A2">A2</option>
            <option value="B1">B1</option>
            <option value="B2">B2</option>
            <option value="C1">C1</option>
            <option value="C2">C2</option>
          </select>
        </label>
        <label className="field">
          <span className="field-label">Language</span>
          <select
            value={language}
            onChange={(e) => setLanguage(e.target.value)}
            disabled={loading}
            className="field-select"
          >
            <option value="en">English</option>
            <option value="es">Spanish</option>
            <option value="ko">Korean</option>
            <option value="tr">Turkish</option>
            <option value="ar">Arabic</option>
            <option value="zh">Chinese</option>
          </select>
        </label>
        <label className="field">
          <span className="field-label">Target words (optional, comma-separated)</span>
          <input
            value={targetWordsText}
            onChange={(e) => setTargetWordsText(e.target.value)}
            placeholder="airport, ticket"
            disabled={loading}
            className="field-input"
          />
        </label>
        {fieldError && <p style={{ color: "var(--warning)" }}>{fieldError}</p>}
        {error && (
          <p style={{ color: "var(--error)", marginTop: 8 }}>
            {error}{" "}
            {lastActionRef.current && (
              <button
                type="button"
                className="btn btn-small btn-outline"
                style={{ marginLeft: 8 }}
                onClick={() => {
                  if (lastActionRef.current) {
                    lastActionRef.current();
                  }
                }}
              >
                Retry last generate
              </button>
            )}
          </p>
        )}
        <button type="submit" disabled={loading} className="btn btn-primary btn-pill">
          {loading ? "Generating…" : "Generate"}
        </button>
      </form>
    </div>
  );
}
