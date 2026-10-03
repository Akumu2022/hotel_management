/** Keeps one broken part (a map, a lazy chunk on a bad connection) from blanking the page. */
import { Component, type ErrorInfo, type ReactNode } from "react";

type Props = { children: ReactNode; fallback?: (reset: () => void) => ReactNode };

export class ErrorBoundary extends Component<Props, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("UI error", error, info.componentStack);
  }

  reset = () => this.setState({ failed: false });

  render() {
    if (!this.state.failed) return this.props.children;
    if (this.props.fallback) return this.props.fallback(this.reset);
    return (
      <main className="flex min-h-dvh flex-col items-center justify-center gap-4 bg-page p-6 text-center text-ink">
        <p className="text-lg font-bold">Something went wrong on this page</p>
        <p className="max-w-sm text-sm text-muted">Your cart and orders are safe. Reload to try again.</p>
        <button onClick={() => window.location.reload()} className="h-12 rounded-xl bg-brand px-6 font-semibold text-white">
          Reload
        </button>
      </main>
    );
  }
}

/** Fallback for a map that failed to load: the rest of the form keeps working. */
export function MapFailed({ retry }: { retry: () => void }) {
  return (
    <div className="flex flex-col items-center gap-2 rounded-2xl border border-dashed border-line bg-subtle px-4 py-8 text-center text-sm">
      <p className="font-semibold">The map couldn't load</p>
      <p className="text-muted">Check your connection and try again.</p>
      <button type="button" onClick={retry} className="mt-1 h-10 rounded-xl border border-line bg-surface px-4 font-semibold">
        Try again
      </button>
    </div>
  );
}
