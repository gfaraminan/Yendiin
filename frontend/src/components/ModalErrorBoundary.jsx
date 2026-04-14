import React from "react";

export default class ModalErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  componentDidCatch(error) {
    console.error("Modal render error", error);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="fixed inset-0 z-[140] bg-black/80 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="w-full max-w-xl rounded-3xl bg-[#14141a] border border-rose-500/30 p-6 text-white">
            <div className="text-[11px] font-black uppercase tracking-widest text-rose-300">Error al renderizar detalle</div>
            <div className="mt-2 text-[12px] text-white/80">El detalle falló en esta sesión. Cerrá y volvé a abrir el modal.</div>
            <button
              onClick={() => {
                this.setState({ hasError: false });
                if (typeof this.props.onClose === "function") this.props.onClose();
              }}
              className="mt-4 px-4 py-2 rounded-xl bg-white/10 border border-white/10 text-[10px] font-black uppercase"
            >
              Cerrar
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
