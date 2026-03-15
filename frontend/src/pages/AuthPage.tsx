import { FormEvent, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { supabase } from "../lib/supabase";

type Mode = "login" | "register";

function useModeFromQuery(): Mode {
  const search = new URLSearchParams(useLocation().search);
  const mode = search.get("mode");
  return mode === "register" ? "register" : "login";
}

export default function AuthPage() {
  const initialMode = useModeFromQuery();
  const [mode, setMode] = useState<Mode>(initialMode);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setInfo(null);
    setLoading(true);
    try {
      if (mode === "register") {
        const redirectTo =
          typeof window !== "undefined" ? `${window.location.origin}/` : undefined;
        const { error: signUpError } = await supabase.auth.signUp({
          email,
          password,
          options: {
            data: { full_name: name },
            emailRedirectTo: redirectTo,
          },
        });
        if (signUpError) throw signUpError;
        setInfo("Check your email to verify your address, then sign in.");
      } else {
        const { error: signInError } = await supabase.auth.signInWithPassword({
          email,
          password,
        });
        if (signInError) throw signInError;
        navigate("/onboarding", { replace: true });
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Authentication failed. Please try again.";
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="page-card" style={{ maxWidth: 420, margin: "40px auto" }}>
      <h1 className="page-title">{mode === "register" ? "Create your TaleTalk account" : "Sign in to TaleTalk"}</h1>
      <div className="chips-row" style={{ marginBottom: 16 }}>
        <button
          type="button"
          onClick={() => setMode("login")}
          className={`chip-toggle ${mode === "login" ? "chip-toggle--active" : ""}`}
        >
          Sign in
        </button>
        <button
          type="button"
          onClick={() => setMode("register")}
          className={`chip-toggle ${mode === "register" ? "chip-toggle--active" : ""}`}
        >
          Register
        </button>
      </div>
      <form onSubmit={handleSubmit} className="form">
        {mode === "register" && (
          <label className="field">
            <span className="field-label">Name</span>
            <input
              required
              value={name}
              onChange={(e) => setName(e.target.value)}
              disabled={loading}
              className="field-input"
              placeholder="How we should call you"
            />
          </label>
        )}
        <label className="field">
          <span className="field-label">Email</span>
          <input
            required
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            disabled={loading}
            className="field-input"
          />
        </label>
        <label className="field">
          <span className="field-label">Password</span>
          <input
            required
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            disabled={loading}
            className="field-input"
          />
        </label>
        {error && <p style={{ color: "var(--error)" }}>{error}</p>}
        {info && <p style={{ color: "var(--accent)" }}>{info}</p>}
        <button type="submit" disabled={loading} className="btn btn-primary btn-pill" style={{ marginTop: 8 }}>
          {loading ? "Please wait…" : mode === "register" ? "Register" : "Sign in"}
        </button>
      </form>
    </div>
  );
}

