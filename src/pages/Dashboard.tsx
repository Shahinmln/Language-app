import { useEffect, useState } from "react";
import { useAuth } from "../auth/AuthContext";
import { request } from "../api/client";

interface Profile {
  display_name?: string | null;
  native_language?: string | null;
  learning_languages?: string[] | null;
  about?: string | null;
  plan?: string | null;
  public_profile?: boolean | null;
  words_learned?: number | null;
  stories_completed?: number | null;
}

interface StrengthWeakness {
  language: string;
  level: string;
  topic: string;
  avg_score: number;
  tests: number;
}

interface DashboardGoals {
  weekly_goal: number;
  weekly_sessions: number;
  weekly_goal_met: boolean;
  current_streak_days: number;
  longest_streak_days: number;
}

interface DashboardSummary {
  strengths: StrengthWeakness[];
  weaknesses: StrengthWeakness[];
  goals: DashboardGoals | null;
  suggestions: string[];
}

interface LeaderboardEntry {
  name: string;
  weekly_xp: number;
  weekly_sessions: number;
}

export default function Dashboard() {
  const { user } = useAuth();
  const [profile, setProfile] = useState<Profile | null>(null);
  const [loading, setLoading] = useState(false);
  const [billingError, setBillingError] = useState<string | null>(null);
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [leaderboard, setLeaderboard] = useState<LeaderboardEntry[]>([]);

  useEffect(() => {
    if (!user) return;
    setLoading(true);
    Promise.all([
      request<{ profile: Profile | null }>(`/api/profile/${user.id}`),
      request<DashboardSummary>(`/api/dashboard-summary?user_id=${user.id}`),
      request<{ entries: LeaderboardEntry[] }>("/api/leaderboard/weekly"),
    ])
      .then(([profileRes, summaryRes, leaderboardRes]) => {
        setProfile(profileRes.profile);
        setSummary(summaryRes);
        setLeaderboard(leaderboardRes.entries ?? []);
      })
      .catch(() => {
        // If personalization fails, still show the dashboard without it.
      })
      .finally(() => setLoading(false));
  }, [user?.id]);

  if (!user) {
    return <p className="page-subtitle">Sign in to view your dashboard.</p>;
  }

  const plan = profile?.plan ?? "free";

  const startCheckout = async (planToBuy: "monthly" | "annual") => {
    setBillingError(null);
    try {
      const res = await request<{ checkout_url: string }>("/api/billing/checkout", {
        method: "POST",
        body: JSON.stringify({
          user_id: user.id,
          plan: planToBuy,
        }),
      });
      window.location.href = res.checkout_url;
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Unable to start checkout. Please try again.";
      setBillingError(msg);
    }
  };

  return (
    <div className="page-card">
      <h1 className="page-title">Your learning space</h1>
      <p className="page-subtitle">
        Welcome back, {profile?.display_name || user.user_metadata?.full_name || user.user_metadata?.name || user.email}. Choose the plan that fits you and continue from where you left off.
      </p>
      {billingError && <p style={{ color: "var(--error)", marginBottom: 12 }}>{billingError}</p>}
      <div style={{ display: "flex", flexWrap: "wrap", gap: 16, marginBottom: 24 }}>
        <div className="card" style={{ flex: "1 1 220px", opacity: plan === "free" ? 1 : 0.85 }}>
          <div className="card-title">Free</div>
          <p className="page-subtitle" style={{ marginTop: 4, fontSize: 13 }}>
            Try TaleTalk with 2 generated stories.
          </p>
          <p style={{ fontSize: 24, margin: "8px 0" }}>$0</p>
          <ul style={{ fontSize: 13, color: "var(--text-secondary)", paddingLeft: 18 }}>
            <li>Up to 2 story generations (lifetime)</li>
            <li>Basic word tracking and vocabulary</li>
            <li>Access to quizzes for your stories</li>
            <li style={{ opacity: 0.7 }}>Limited personalization and stats</li>
          </ul>
          {plan === "free" && <span className="card-badge">Current plan</span>}
        </div>
        <div
          className="card"
          style={{
            flex: "1 1 220px",
            borderColor: "rgba(250, 204, 21, 0.9)",
            boxShadow: "0 22px 55px rgba(251, 191, 36, 0.5)",
          }}
        >
          <div className="card-ribbon">Most popular</div>
          <div className="card-title">Monthly Pro</div>
          <p className="page-subtitle" style={{ marginTop: 4, fontSize: 13 }}>
            Unlimited stories and smart practice, cancel anytime.
          </p>
          <p style={{ fontSize: 24, margin: "8px 0" }}>$5 / month</p>
          <ul style={{ fontSize: 13, color: "var(--text-secondary)", paddingLeft: 18 }}>
            <li>Unlimited story generations in all supported languages</li>
            <li>Full vocabulary and test history, with wrong answers highlighted</li>
            <li>Deeper personalization based on your goals and reading history</li>
            <li>New features rolled out to Pro users first</li>
          </ul>
          <button className="btn btn-primary btn-pill" style={{ marginTop: 8 }} onClick={() => startCheckout("monthly")}>
            Unlock unlimited stories
          </button>
        </div>
        <div
          className="card"
          style={{
            flex: "1 1 220px",
            borderColor: "rgba(52, 211, 153, 1)",
            boxShadow: "0 26px 70px rgba(16, 185, 129, 0.65)",
          }}
        >
          <div className="card-ribbon card-ribbon--strong">Best value</div>
          <div className="card-title">Annual Pro</div>
          <p className="page-subtitle" style={{ marginTop: 4, fontSize: 13 }}>
            Best value for dedicated learners.
          </p>
          <p style={{ fontSize: 24, margin: "8px 0" }}>$50 / year</p>
          <ul style={{ fontSize: 13, color: "var(--text-secondary)", paddingLeft: 18 }}>
            <li>Everything in Monthly Pro, with a year of focus</li>
            <li>Unlimited story generations and quiz attempts</li>
            <li>Full test history so you can see progress over months</li>
            <li>Save over 15% compared to paying monthly</li>
          </ul>
          <button className="btn btn-primary btn-pill" style={{ marginTop: 8 }} onClick={() => startCheckout("annual")}>
            Go annual and save
          </button>
        </div>
      </div>
      <div>
        <h2 className="page-subtitle" style={{ marginBottom: 8 }}>
          Your languages
        </h2>
        {loading && <p className="page-subtitle">Loading profile…</p>}
        {!loading && (
          <p style={{ fontSize: 14, color: "var(--text-secondary)" }}>
            Native: {profile?.native_language || "not set"} · Learning:{" "}
            {(profile?.learning_languages && profile.learning_languages.join(", ")) || "not set"}
          </p>
        )}
      </div>

      {summary && (
        <div style={{ marginTop: 24, display: "grid", gap: 16 }}>
          <div className="card" style={{ padding: 16 }}>
            <div className="card-title">Your goals & streaks</div>
            {summary.goals ? (
              <p style={{ fontSize: 14, color: "var(--text-secondary)", marginTop: 6 }}>
                Weekly goal: {summary.goals.weekly_goal} sessions · This week:{" "}
                {summary.goals.weekly_sessions}{" "}
                {summary.goals.weekly_goal_met ? "(goal reached 🎉)" : "(keep going!)"}
                <br />
                Current streak: {summary.goals.current_streak_days} day
                {summary.goals.current_streak_days === 1 ? "" : "s"} · Longest streak:{" "}
                {summary.goals.longest_streak_days} day
                {summary.goals.longest_streak_days === 1 ? "" : "s"}
              </p>
            ) : (
              <p style={{ fontSize: 14, color: "var(--text-secondary)", marginTop: 6 }}>
                Start completing stories to build your first streak.
              </p>
            )}
          </div>

          {summary.suggestions.length > 0 && (
            <div className="card" style={{ padding: 16 }}>
              <div className="card-title">Today&apos;s focus</div>
              <ul style={{ marginTop: 8, paddingLeft: 18, fontSize: 14, color: "var(--text-secondary)" }}>
                {summary.suggestions.map((s, idx) => (
                  <li key={idx}>{s}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {profile && (
        <div style={{ marginTop: 24, display: "grid", gap: 16 }}>
          <div className="card" style={{ padding: 16 }}>
            <div className="card-title">Your stats</div>
            <p style={{ fontSize: 14, color: "var(--text-secondary)", marginTop: 6 }}>
              Words learned: {profile.words_learned ?? 0} · Stories completed: {profile.stories_completed ?? 0}
            </p>
          </div>

          <div className="card" style={{ padding: 16 }}>
            <div className="card-title">Social & privacy</div>
            <p style={{ fontSize: 13, color: "var(--text-secondary)", marginBottom: 8 }}>
              You can choose to appear on the weekly leaderboard. Only your display name (or an anonymous label) and
              study stats are visible — never your email or detailed history.
            </p>
            <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 14 }}>
              <input
                type="checkbox"
                checked={!!profile.public_profile}
                onChange={async (e) => {
                  if (!user || !profile) return;
                  const next = e.target.checked;
                  try {
                    await request<{ success: boolean }>("/api/profile", {
                      method: "POST",
                      body: JSON.stringify({
                        user_id: user.id,
                        native_language: profile.native_language,
                        learning_languages: profile.learning_languages,
                        about: profile.about,
                        plan: profile.plan,
                        public_profile: next,
                      }),
                    });
                    setProfile({ ...profile, public_profile: next });
                  } catch {
                    // best-effort; swallow error
                  }
                }}
              />
              <span>Appear on weekly leaderboard</span>
            </label>
          </div>
        </div>
      )}

      {leaderboard.length > 0 && (
        <div style={{ marginTop: 24 }}>
          <div className="card" style={{ padding: 16 }}>
            <div className="card-title">Weekly leaderboard</div>
            <p style={{ fontSize: 13, color: "var(--text-secondary)", marginTop: 4 }}>
              Based on stories completed in the last 7 days. Names are anonymized unless users set a display name.
            </p>
            <ol style={{ marginTop: 8, paddingLeft: 20, fontSize: 14, color: "var(--text-secondary)" }}>
              {leaderboard.map((entry, idx) => (
                <li key={`${entry.name}-${idx}`} style={{ marginBottom: 4 }}>
                  <strong>{entry.name}</strong> — {entry.weekly_xp} XP · {entry.weekly_sessions}{" "}
                  {entry.weekly_sessions === 1 ? "session" : "sessions"}
                </li>
              ))}
            </ol>
          </div>
        </div>
      )}
    </div>
  );
}

