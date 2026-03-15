import { Component, ReactNode } from "react";

interface ErrorBoundaryProps {
  children: ReactNode;
}

interface ErrorBoundaryState {
  hasError: boolean;
}

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(): ErrorBoundaryState {
    return { hasError: true };
  }

  componentDidCatch(error: unknown, info: unknown) {
    // eslint-disable-next-line no-console
    console.error("ErrorBoundary caught error", error, info);
  }

  handleRetry = () => {
    // Simple pattern: reset error boundary and let children re-render.
    this.setState({ hasError: false });
  };

  render() {
    if (this.state.hasError) {
      return (
        <div className="page-full-center" role="alert">
          <div className="page-card" style={{ maxWidth: 480 }}>
            <h1 className="page-title">We&apos;re saving your progress</h1>
            <p className="page-subtitle">
              Something went wrong while talking to the server. Your work should be safe. Please try again in a moment.
            </p>
            <button type="button" className="btn btn-primary btn-pill" onClick={this.handleRetry}>
              Try again
            </button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}

