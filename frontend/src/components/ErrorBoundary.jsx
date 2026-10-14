import React from "react";
import { ShieldAlert, RotateCcw, AlertTriangle, Bug } from "lucide-react";

/**
 * Robust React Error Boundary component.
 * Catches unhandled JavaScript exceptions in child component trees
 * and presents an actionable recovery UI instead of an unmounted black screen.
 */
export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = {
      hasError: false,
      error: null,
      errorInfo: null,
    };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, errorInfo) {
    console.error("ErrorBoundary caught an unhandled runtime exception:", error, errorInfo);
    this.setState({ error, errorInfo });
  }

  handleReset = () => {
    this.setState({ hasError: false, error: null, errorInfo: null });
    if (this.props.onReset) {
      this.props.onReset();
    } else {
      window.location.reload();
    }
  };

  render() {
    if (this.state.hasError) {
      const { error } = this.state;
      return (
        <div
          style={{
            height: "100vh",
            width: "100vw",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            backgroundColor: "var(--bg-app, #080d14)",
            color: "var(--text-main, #f8fafc)",
            fontFamily: "var(--font-sans, sans-serif)",
            padding: "24px",
            boxSizing: "border-box",
          }}
        >
          <div
            style={{
              maxWidth: "560px",
              width: "100%",
              background: "var(--bg-panel, #0f1a26)",
              border: "1px solid rgba(244, 63, 94, 0.4)",
              borderTop: "4px solid var(--status-rose, #f43f5e)",
              borderRadius: "var(--radius-lg, 10px)",
              padding: "24px 28px",
              boxShadow: "0 10px 30px rgba(0, 0, 0, 0.6)",
              display: "flex",
              flexDirection: "column",
              gap: "16px",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
              <div
                style={{
                  width: "40px",
                  height: "40px",
                  borderRadius: "8px",
                  background: "rgba(244, 63, 94, 0.15)",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  flexShrink: 0,
                }}
              >
                <ShieldAlert size={22} color="var(--status-rose, #f43f5e)" />
              </div>
              <div>
                <h2 style={{ fontSize: "16px", fontWeight: 700, margin: 0, color: "#ffffff" }}>
                  Workspace Render Exception Caught
                </h2>
                <p style={{ fontSize: "12px", color: "var(--text-muted, #94a3b8)", margin: "2px 0 0" }}>
                  GeoRoute AI encountered an unexpected UI rendering error.
                </p>
              </div>
            </div>

            <div
              style={{
                background: "rgba(0, 0, 0, 0.35)",
                border: "1px solid rgba(255, 255, 255, 0.08)",
                borderRadius: "var(--radius-md, 6px)",
                padding: "12px 14px",
                fontSize: "12px",
                color: "#fca5a5",
                fontFamily: "var(--font-mono, monospace)",
                wordBreak: "break-word",
                maxHeight: "140px",
                overflowY: "auto",
              }}
            >
              <strong>{error?.name || "Error"}:</strong> {error?.message || "Unknown error occurred"}
            </div>

            <p style={{ fontSize: "11.5px", color: "var(--text-dim, #64748b)", margin: 0, lineHeight: 1.45 }}>
              The application state was protected from a hard browser crash. You can reset the workspace state or reload the dashboard.
            </p>

            <div style={{ display: "flex", alignItems: "center", gap: "10px", marginTop: "4px" }}>
              <button
                type="button"
                className="btn btn-primary btn-sm"
                onClick={this.handleReset}
                style={{
                  background: "linear-gradient(135deg, #0d9488 0%, #0891b2 100%)",
                  color: "#ffffff",
                  border: "none",
                  padding: "8px 16px",
                  borderRadius: "6px",
                  cursor: "pointer",
                  display: "inline-flex",
                  alignItems: "center",
                  gap: "6px",
                  fontWeight: 600,
                  fontSize: "12px",
                }}
              >
                <RotateCcw size={14} />
                <span>Recover & Reload Workspace</span>
              </button>
            </div>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
