import { useEffect, useRef, useState } from "react";
import { useParams, useNavigate, useLocation } from "react-router-dom";
import {
  getStory,
  getUserWords,
  trackWord,
  trackInteraction,
  simplifyStory,
  getStoryWordBank,
  type Story,
  type WordBankItem,
} from "../api/client";
import { useAuth } from "../auth/AuthContext";

function WordTooltip({
  word,
  definition,
  translation,
  example,
  pos,
  onClose,
  onTrackClicked,
  onTrackLearned,
}: {
  word: string;
  definition?: string | null;
  translation?: string | null;
  example?: string | null;
  pos?: string | null;
  onClose: () => void;
  onTrackClicked: () => void;
  onTrackLearned: () => void;
}) {
  const titleId = `word-tooltip-title-${word}`;
  const descriptionId = `word-tooltip-body-${word}`;
  return (
    <div className="modal-backdrop" onClick={onClose} role="presentation">
      <div
        className="modal-card"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={descriptionId}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-header">
          <div>
            <strong className="modal-title" id={titleId}>
              {word}
            </strong>
            {pos && <span className="modal-pos">({pos})</span>}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="btn btn-small btn-outline"
            aria-label="Close word details"
          >
            ✕
          </button>
        </div>
        <div id={descriptionId}>
          {definition != null && definition !== "" && <p style={{ margin: "8px 0" }}>{definition}</p>}
          {translation != null && translation !== "" && (
            <p style={{ margin: "8px 0", color: "var(--text-secondary)", fontSize: 14 }}>{translation}</p>
          )}
          {example != null && example !== "" && (
            <p
              style={{
                margin: "8px 0",
                padding: 8,
                background: "var(--bg-secondary)",
                borderRadius: 6,
                fontStyle: "italic",
                fontSize: 14,
              }}
            >
              "{example}"
            </p>
          )}
        </div>
        <div className="chips-row" style={{ marginTop: 16 }}>
          <button type="button" onClick={onTrackClicked} className="btn btn-small btn-outline">
            Track clicked
          </button>
          <button
            type="button"
            onClick={onTrackLearned}
            className="btn btn-small"
            style={{ background: "var(--success)", color: "white" }}
          >
            I know it
          </button>
        </div>
      </div>
    </div>
  );
}

export default function StoryReader() {
  const { storyId } = useParams<{ storyId: string }>();
  const navigate = useNavigate();
  const location = useLocation();
  const { user } = useAuth();
  const [story, setStory] = useState<Story | null>(location.state?.story ?? null);
  const [loading, setLoading] = useState(!location.state?.story);
  const [error, setError] = useState<string | null>(null);
  const [selectedWord, setSelectedWord] = useState<{ word: string; definition?: string | null; translation?: string | null; example?: string | null; pos?: string | null } | null>(null);
  const [audioError, setAudioError] = useState(false);
  const [userWordStatusMap, setUserWordStatusMap] = useState<Map<string, string>>(new Map());
  const pollIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const pollTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [shadowMode, setShadowMode] = useState(false);
  const [simplifyLoading, setSimplifyLoading] = useState(false);
  const [simplifiedStory, setSimplifiedStory] = useState<Story | null>(null);
  const [showSimplified, setShowSimplified] = useState(false);
  const [wordBank, setWordBank] = useState<WordBankItem[]>([]);
  const [hideMastered, setHideMastered] = useState(false);

  useEffect(() => {
    const stateStoryId = (location.state as { storyId?: string } | null)?.storyId;
    if (story && storyId && (story.id === storyId || stateStoryId === storyId)) return;
    if (!storyId) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    getStory(storyId)
      .then((res) => {
        if (!cancelled && res.story) setStory(res.story);
      })
      .catch((e) => { if (!cancelled) setError(e instanceof Error ? e.message : "Failed to load"); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [storyId, story?.id]);

  // Fetch user vocabulary for word-status highlighting
  useEffect(() => {
    if (!story || !user) return;
    let cancelled = false;
    getUserWords(user.id, { target_language: story.target_language ?? undefined })
      .then((res) => {
        const words = res.words ?? [];
        const map = new Map<string, string>();
        for (const w of words) {
          const word = (w as { word?: string }).word;
          const status = (w as { status?: string }).status;
          if (typeof word === "string" && typeof status === "string") {
            map.set(word.toLowerCase().trim(), status);
          }
        }
        if (!cancelled) setUserWordStatusMap(map);
      })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [story?.id, story?.target_language, user?.id]);

  // Fetch word bank for this story
  useEffect(() => {
    if (!storyId || !user) return;
    let cancelled = false;
    getStoryWordBank(storyId, user.id, story?.target_language ?? undefined)
      .then((res) => {
        if (!cancelled) setWordBank(res.words ?? []);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [storyId, story?.id, story?.target_language, user?.id]);

  // Poll for audio_url when story is loaded but audio not yet available (background TTS). Stop when audio_url set or after 60s.
  useEffect(() => {
    if (!storyId || !story) return;
    if (story.audio_url) return;

    const POLL_MS = 5000;
    const MAX_POLL_MS = 60000;

    const poll = () => {
      getStory(storyId)
        .then((res) => {
          if (res.story) setStory(res.story);
        })
        .catch(() => {});
    };

    pollIntervalRef.current = setInterval(poll, POLL_MS);
    pollTimeoutRef.current = setTimeout(() => {
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
        pollIntervalRef.current = null;
      }
    }, MAX_POLL_MS);

    return () => {
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
        pollIntervalRef.current = null;
      }
      if (pollTimeoutRef.current) {
        clearTimeout(pollTimeoutRef.current);
        pollTimeoutRef.current = null;
      }
    };
  }, [storyId, story?.id, story?.audio_url]);

  const statusToClass = (status: string): string => {
    switch (status) {
      case "want_to_learn":
      case "learning":
        return "word-learning";
      case "reviewing":
        return "word-review";
      case "mastered":
        return "word-mastered";
      default:
        return "word-new";
    }
  };

  const vocabulary = (story?.vocabulary != null && Array.isArray(story.vocabulary)) ? story.vocabulary as Array<{ word?: string; definition?: string; translation?: string; example?: string; pos?: string }> : [];
  const vocabMap = new Map(vocabulary.map((v) => [String(v.word ?? "").toLowerCase(), v]));

  const handleWordClick = (w: string) => {
    const v = vocabMap.get(w.toLowerCase()) ?? {};
    setSelectedWord({
      word: w,
      definition: v.definition,
      translation: v.translation,
      example: v.example,
      pos: v.pos,
    });
  };

  const handleTrackClicked = () => {
    if (!selectedWord || !storyId || !user) return;
    trackWord({ user_id: user.id, word: selectedWord.word, action: "clicked", story_id: storyId }).catch(() => {});
    setSelectedWord(null);
  };

  const handleTrackLearned = () => {
    if (!selectedWord || !storyId || !user) return;
    trackWord({ user_id: user.id, word: selectedWord.word, action: "learned", story_id: storyId }).catch(() => {});
    setSelectedWord(null);
  };

  const activeStory = showSimplified && simplifiedStory ? simplifiedStory : story;

  useEffect(() => {
    if (storyId && user) trackInteraction({ user_id: user.id, story_id: storyId, action: "play" }).catch(() => {});
  }, [storyId, user?.id]);

  const content = activeStory?.content ?? "";
  const transcript = activeStory?.transcript_json;
  const hasTranscript = Array.isArray(transcript) && transcript.length > 0;
  const displayParts = hasTranscript
    ? (transcript as Array<{ sentence?: string }>).flatMap((t) => (t.sentence ?? "").split(/(\s+)/)).filter(Boolean)
    : content.split(/(\s+)/);

  const audioUrl = activeStory?.audio_url && !audioError ? activeStory.audio_url : null;
  const patterns =
    activeStory && Array.isArray((activeStory as any).patterns)
      ? ((activeStory as any).patterns as Array<{ structure?: string; explanation?: string; examples?: string[] }>)
      : [];
  const shadowSentences = hasTranscript
    ? (transcript as Array<{ sentence?: string }>)
        .map((t) => (t.sentence ?? "").trim())
        .filter((s) => s.length > 0)
    : [];

  const handleSimplifyToggle = async () => {
    if (!storyId || !story) return;
    if (simplifiedStory) {
      // Already have it; just toggle view.
      setShowSimplified((prev) => !prev);
      return;
    }
    setSimplifyLoading(true);
    try {
      const res = await simplifyStory(storyId);
      setSimplifiedStory(res.story);
      setShowSimplified(true);
    } catch (e) {
      // best-effort; ignore errors
    } finally {
      setSimplifyLoading(false);
    }
  };

  if (loading) return <p className="page-subtitle">Loading story…</p>;
  if (error || !story) return <p style={{ color: "var(--error)" }}>{error ?? "Story not found"}</p>;

  return (
    <div className="page-card">
      <button
        type="button"
        onClick={() => {
          if (storyId && user) {
            // Best-effort analytics: user left the story without an explicit completion signal.
            trackInteraction({ user_id: user.id, story_id: storyId, action: "abandon" }).catch(() => {});
          }
          navigate(-1);
        }}
        className="btn btn-small btn-outline"
        style={{ marginBottom: 16 }}
      >
        ← Back
      </button>
      <h1 className="page-title">{activeStory?.title ?? "Untitled"}</h1>
      <p className="page-subtitle" style={{ fontSize: 14 }}>
        {activeStory?.cefr_level} · {activeStory?.duration_minutes ?? 0} min · {activeStory?.topic} ·{" "}
        {activeStory?.target_language}
      </p>
      {audioUrl ? (
        <div style={{ marginBottom: 24 }}>
          <audio controls src={audioUrl} onError={() => setAudioError(true)} style={{ width: "100%", maxWidth: 400 }}>
            Your browser does not support audio.
          </audio>
          {shadowSentences.length > 0 && (
            <button
              type="button"
              className="btn btn-small btn-outline"
              style={{ marginTop: 8 }}
              onClick={() => setShadowMode((prev) => !prev)}
            >
              {shadowMode ? "Hide shadowing mode" : "Practice shadowing"}
            </button>
          )}
        </div>
      ) : (
        <p style={{ color: "var(--text-muted)", fontSize: 14, marginBottom: 24 }}>No audio for this story.</p>
      )}
      {shadowMode && shadowSentences.length > 0 && (
        <div style={{ marginBottom: 24 }}>
          <h2 className="page-subtitle" style={{ marginBottom: 8 }}>
            Shadowing practice
          </h2>
          <p style={{ fontSize: 13, color: "var(--text-secondary)", marginBottom: 12 }}>
            1) Play the audio. 2) Pause after each sentence and repeat it out loud. Focus on rhythm and pronunciation.
          </p>
          <ul style={{ listStyle: "decimal", paddingLeft: 20, fontSize: 14 }}>
            {shadowSentences.slice(0, 6).map((s, idx) => (
              <li key={idx} style={{ marginBottom: 6 }}>
                {s}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="chips-row" style={{ marginBottom: 16 }}>
        <button
          type="button"
          className="btn btn-small btn-outline"
          onClick={handleSimplifyToggle}
          disabled={simplifyLoading}
        >
          {simplifyLoading
            ? "Simplifying…"
            : showSimplified
            ? "Show original story"
            : "Need it easier? Simplify"}
        </button>
        <button
          type="button"
          className="btn btn-small btn-outline"
          onClick={async () => {
            try {
              const url = window.location.href;
              if (navigator.share) {
                await navigator.share({ url, title: activeStory?.title ?? "TaleTalk story" });
              } else if (navigator.clipboard) {
                await navigator.clipboard.writeText(url);
              }
            } catch {
              // ignore share errors
            }
          }}
        >
          Study together – share this story
        </button>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "2.3fr 1fr", gap: 24 }}>
        <div style={{ fontSize: 18, lineHeight: 1.75 }}>
        {displayParts.map((part, i) => {
          const isWord = /^\S+$/.test(part) && part.length > 0;
          if (isWord) {
            const status = userWordStatusMap.get(part.toLowerCase()) ?? "new";
            const statusClass = statusToClass(status);
            return (
              <span key={i}>
                <span
                  role="button"
                  tabIndex={0}
                  className={statusClass}
                  onClick={() => handleWordClick(part)}
                  onKeyDown={(e) => e.key === "Enter" && handleWordClick(part)}
                  style={{ cursor: "pointer", textDecoration: "underline", textUnderlineOffset: 2 }}
                >
                  {part}
                </span>
                {part !== "" && " "}
              </span>
            );
          }
          return <span key={i}>{part}</span>;
        })}
      </div>

        <aside
          className="card"
          style={{
            padding: 12,
            alignSelf: "flex-start",
            maxHeight: 420,
            overflowY: "auto",
            fontSize: 13,
          }}
        >
          <div className="card-title">Word bank</div>
          <p style={{ fontSize: 12, color: "var(--text-secondary)", margin: "4px 0 8px" }}>
            Key words from this story, color-coded by status. Click any word in the text to see details.
          </p>
          <div className="chips-row" style={{ marginBottom: 8 }}>
            <button
              type="button"
              className="btn btn-small btn-outline"
              onClick={() => {
                // Quick action: focus review now → open Review page in a new tab.
                window.open("/review", "_blank", "noopener,noreferrer");
              }}
            >
              Review these words now
            </button>
            <button
              type="button"
              className="btn btn-small btn-outline"
              onClick={() => setHideMastered((prev) => !prev)}
            >
              {hideMastered ? "Show mastered" : "Hide mastered words"}
            </button>
          </div>
          <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
            {wordBank
              .filter((w) => (hideMastered ? w.status !== "mastered" : true))
              .map((w) => {
                const status = w.status ?? "new";
                const statusClass = statusToClass(status);
                return (
                  <li
                    key={w.word}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 8,
                      marginBottom: 4,
                    }}
                  >
                    <span className={statusClass} style={{ padding: "2px 6px", borderRadius: 4, fontSize: 12 }}>
                      {w.word}
                    </span>
                    <span style={{ fontSize: 11, color: "var(--text-secondary)", flex: 1, minWidth: 0 }}>
                      {w.translation || w.definition || ""}
                    </span>
                  </li>
                );
              })}
          </ul>
        </aside>
      </div>
      {patterns.length > 0 && (
        <div style={{ marginTop: 24 }}>
          <h2 className="page-subtitle" style={{ marginBottom: 8 }}>
            Grammar & patterns
          </h2>
          {patterns.slice(0, 2).map((p, idx) => (
            <div key={idx} className="card" style={{ marginBottom: 8 }}>
              {p.structure && <div className="card-title">{p.structure}</div>}
              {p.explanation && (
                <p style={{ fontSize: 14, color: "var(--text-secondary)", margin: "4px 0 8px" }}>{p.explanation}</p>
              )}
              {Array.isArray(p.examples) && p.examples.length > 0 && (
                <ul style={{ fontSize: 13, color: "var(--text-muted)", paddingLeft: 16, margin: 0 }}>
                  {p.examples.slice(0, 2).map((ex, i) => (
                    <li key={i}>{ex}</li>
                  ))}
                </ul>
              )}
            </div>
          ))}
        </div>
      )}
      {selectedWord && (
        <WordTooltip
          word={selectedWord.word}
          definition={selectedWord.definition}
          translation={selectedWord.translation}
          example={selectedWord.example}
          pos={selectedWord.pos}
          onClose={() => setSelectedWord(null)}
          onTrackClicked={handleTrackClicked}
          onTrackLearned={handleTrackLearned}
        />
      )}
    </div>
  );
}
