import { Routes, Route, Link, Navigate, useLocation } from "react-router-dom";
import Explore from "./pages/Explore";
import GenerateStory from "./pages/GenerateStory";
import StoryReader from "./pages/StoryReader";
import Vocabulary from "./pages/Vocabulary";
import Landing from "./pages/Landing";
import AuthPage from "./pages/AuthPage";
import Onboarding from "./pages/Onboarding";
import Dashboard from "./pages/Dashboard";
import HistoryPage from "./pages/HistoryPage";
import TestsPage from "./pages/TestsPage";
import ReviewPage from "./pages/ReviewPage";
import { useAuth } from "./auth/AuthContext";
import { ErrorBoundary } from "./components/ErrorBoundary";

function Nav() {
  const { user } = useAuth();
  const location = useLocation();
  const path = location.pathname;
  const isSignedIn = user && (user as { email_confirmed_at?: string | null }).email_confirmed_at;
  return (
    <nav className="nav">
      <span className="nav-logo">TaleTalk</span>
      <div className="nav-links">
        <Link to="/" className={`nav-link ${path === "/" ? "nav-link--active" : ""}`}>Home</Link>
        {isSignedIn && (
          <>
            <Link to="/dashboard" className={`nav-link ${path.startsWith("/dashboard") ? "nav-link--active" : ""}`}>Dashboard</Link>
            <Link to="/explore" className={`nav-link ${path.startsWith("/explore") ? "nav-link--active" : ""}`}>Explore</Link>
            <Link to="/generate" className={`nav-link ${path.startsWith("/generate") ? "nav-link--active" : ""}`}>Generate</Link>
            <Link to="/review" className={`nav-link ${path.startsWith("/review") ? "nav-link--active" : ""}`}>Review</Link>
            <Link to="/history" className={`nav-link ${path.startsWith("/history") ? "nav-link--active" : ""}`}>History</Link>
            <Link to="/tests" className={`nav-link ${path.startsWith("/tests") ? "nav-link--active" : ""}`}>Tests</Link>
            <Link to="/vocabulary" className={`nav-link ${path.startsWith("/vocabulary") ? "nav-link--active" : ""}`}>Vocabulary</Link>
          </>
        )}
      </div>
      <span className="nav-user">
        {isSignedIn ? (user!.user_metadata?.full_name || user!.user_metadata?.name || user!.email) : "Guest"}
      </span>
    </nav>
  );
}

export default function App() {
  const { user } = useAuth();
  return (
    <ErrorBoundary>
      <Nav />
      <main className="layout-main">
        <Routes>
          <Route
            path="/"
            element={user ? <Explore /> : <Landing />}
          />
          <Route path="/auth" element={<AuthPage />} />
          <Route path="/onboarding" element={<Onboarding />} />
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/explore" element={<Explore />} />
          <Route path="/generate" element={<GenerateStory />} />
          <Route path="/review" element={<ReviewPage />} />
          <Route path="/history" element={<HistoryPage />} />
          <Route path="/tests" element={<TestsPage />} />
          <Route path="/story/:storyId" element={<StoryReader />} />
          <Route path="/vocabulary" element={<Vocabulary />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </ErrorBoundary>
  );
}
