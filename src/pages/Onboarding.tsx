import { FormEvent, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { request } from "../api/client"; // we'll expose a light helper if needed

const SUPPORTED_LANGUAGES = [
  { code: "en", label: "English" },
  { code: "es", label: "Spanish" },
  { code: "ko", label: "Korean" },
  { code: "tr", label: "Turkish" },
  { code: "ar", label: "Arabic" },
  { code: "zh", label: "Chinese" },
];

export default function Onboarding() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [nativeLanguage, setNativeLanguage] = useState("en");
  const [learningLanguages, setLearningLanguages] = useState<string[]>(["en"]);
  const [about, setAbout] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!user) return;
    // Optionally, you could prefetch an existing profile here.
  }, [user]);

  const toggleLearningLanguage = (code: string) => {
    setLearningLanguages((prev) =>
      prev.includes(code) ? prev.filter((c) => c !== code) : [...prev, code]
    );
  };

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!user) return;
    setLoading(true);
    setError(null);
    try {
      await request<{ success: boolean }>("/api/profile", {
        method: "POST",
        body: JSON.stringify({
          user_id: user.id,
          native_language: nativeLanguage,
          learning_languages: learningLanguages,
          about: about || "",
          display_name: user.user_metadata?.full_name || user.user_metadata?.name || "",
        }),
      });
      navigate("/", { replace: true });
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to save your profile.";
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  if (!user) {
    return <p className="page-subtitle" style={{ padding: 24 }}>Sign in to continue.</p>;
  }

  return (
    <div className="page-card" style={{ maxWidth: 520, margin: "32px auto" }}>
      <h1 className="page-title">
        Welcome, {user.user_metadata?.full_name || user.user_metadata?.name || user.email}
      </h1>
      <p className="page-subtitle">
        Tell TaleTalk a bit about you so we can adapt stories to your languages and interests.
      </p>
      <form onSubmit={handleSubmit} className="form">
        <label className="field">
          <span className="field-label">Your native language</span>
          <select
            required
            value={nativeLanguage}
            onChange={(e) => setNativeLanguage(e.target.value)}
            disabled={loading}
            className="field-select"
          >
            {SUPPORTED_LANGUAGES.map((lang) => (
              <option key={lang.code} value={lang.code}>
                {lang.label}
              </option>
            ))}
          </select>
        </label>
        <div>
          <p className="field-label">Languages you want to learn</p>
          <div className="chips-row">
            {SUPPORTED_LANGUAGES.map((lang) => (
              <button
                key={lang.code}
                type="button"
                onClick={() => toggleLearningLanguage(lang.code)}
                disabled={loading}
                className={`chip-toggle ${learningLanguages.includes(lang.code) ? "chip-toggle--active" : ""}`}
              >
                {lang.label}
              </button>
            ))}
          </div>
        </div>
        <label className="field">
          <span className="field-label">
            Tell us about yourself (optional — hobbies, goals, how you like to learn)
          </span>
          <textarea
            value={about}
            onChange={(e) => setAbout(e.target.value)}
            disabled={loading}
            rows={4}
            className="field-textarea"
            placeholder="Optional"
          />
        </label>
        {error && <p style={{ color: "var(--error)" }}>{error}</p>}
        <button type="submit" disabled={loading} className="btn btn-primary btn-pill">
          {loading ? "Saving…" : "Save and start exploring"}
        </button>
      </form>
    </div>
  );
}

