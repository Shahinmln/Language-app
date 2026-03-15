import { Link } from "react-router-dom";

export default function Landing() {
  return (
    <div className="page-full-center">
      <h1 className="landing-title">TaleTalk</h1>
      <p className="landing-subtitle">
        AI-powered stories for language learners. Create immersive, level‑matched stories in any language you care about.
      </p>
      <div className="landing-cta-row">
        <Link
          to="/auth?mode=register"
          className="btn btn-primary btn-pill"
        >
          Get started
        </Link>
        <Link
          to="/auth?mode=login"
          className="btn btn-outline btn-pill"
        >
          I already have an account
        </Link>
      </div>
      <p className="landing-footnote">
        No account yet? Register with your email and verify it to save your progress.
      </p>
    </div>
  );
}

