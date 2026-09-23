import { Component, type ErrorInfo, type ReactNode } from "react";

type Props = { children: ReactNode };
type State = { error: Error | null };

/**
 * Evita pantalla blanca ante fallos de red/COM/render.
 * El usuario puede reintentar o recargar sin perder el shell.
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("RECYM SPA ErrorBoundary", error, info.componentStack);
  }

  private retry = () => this.setState({ error: null });

  private reload = () => {
    window.location.reload();
  };

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;

    const msg = error.message || String(error);
    const isCom =
      /cym|com|0xc0000005|access violation|conexión|timeout|abort/i.test(msg);

    return (
      <div className="app-shell" style={{ padding: 32 }}>
        <div className="card" style={{ maxWidth: 560 }}>
          <h2 style={{ marginTop: 0 }}>Algo falló en la interfaz</h2>
          <p className="muted">
            {isCom
              ? "Parece un fallo de red, timeout o CYMDIST/COM. Puede reintentar o reabrir el estudio desde §1."
              : "Error de la aplicación. Puede reintentar sin perder el menú."}
          </p>
          <pre
            style={{
              whiteSpace: "pre-wrap",
              fontSize: 12,
              background: "var(--surface-2, #f4f4f5)",
              padding: 12,
              borderRadius: 6,
              overflow: "auto",
            }}
          >
            {msg}
          </pre>
          <div className="actions" style={{ display: "flex", gap: 8, marginTop: 16 }}>
            <button type="button" onClick={this.retry}>
              Reintentar
            </button>
            <button type="button" className="secondary" onClick={this.reload}>
              Recargar página
            </button>
          </div>
        </div>
      </div>
    );
  }
}
