import { useEffect, useState } from "react";
import { Loader2, Mail, X } from "lucide-react";
import { UI } from "../app/constants";
import { featureFlags } from "../config/features";

export default function GoogleLoginModal({ open, onClose, onLoggedIn, googleClientId }) {
  const [ready, setReady] = useState(false);
  const [tab, setTab] = useState("google");
  const [email, setEmail] = useState("");
  const [emailSending, setEmailSending] = useState(false);
  const [emailSent, setEmailSent] = useState(false);
  const [emailError, setEmailError] = useState("");
  const allowGoogleLogin = featureFlags.googleLogin;
  const allowMagicLinkLogin = featureFlags.magicLinkLogin;

  useEffect(() => {
    if (!allowGoogleLogin && allowMagicLinkLogin) setTab("email");
    if (allowGoogleLogin && !allowMagicLinkLogin) setTab("google");
  }, [allowGoogleLogin, allowMagicLinkLogin]);

  const readJsonOrText = async (r) => {
    const ct = (r.headers.get("content-type") || "").toLowerCase();
    if (ct.includes("application/json")) return await r.json();
    const t = await r.text();
    try {
      return JSON.parse(t);
    } catch {
      return { detail: t };
    }
  };

  useEffect(() => {
    if (!open) return;

    setEmailSent(false);
    setEmailError("");
    setEmailSending(false);

    const ensureScript = () =>
      new Promise((resolve, reject) => {
        if (window.google?.accounts?.id) return resolve(true);
        const id = "google-identity";
        if (document.getElementById(id)) {
          const check = () => {
            if (window.google?.accounts?.id) resolve(true);
            else setTimeout(check, 50);
          };
          check();
          return;
        }
        const s = document.createElement("script");
        s.id = id;
        s.src = "https://accounts.google.com/gsi/client";
        s.async = true;
        s.defer = true;
        s.onload = () => resolve(true);
        s.onerror = () => reject(new Error("No se pudo cargar Google"));
        document.head.appendChild(s);
      });

    (async () => {
      try {
        if (allowGoogleLogin && googleClientId) {
          await ensureScript();
        }
        setReady(true);

        if (allowGoogleLogin && googleClientId && window.google?.accounts?.id) {
          window.google.accounts.id.initialize({
            client_id: googleClientId,
            callback: async (resp) => {
              try {
                const r = await fetch("/api/auth/google", {
                  method: "POST",
                  headers: { "Content-Type": "application/json" },
                  credentials: "include",
                  body: JSON.stringify({ credential: resp.credential }),
                });
                const data = await readJsonOrText(r);
                if (!r.ok) throw new Error((data && data.detail) || "Login falló");

                let u = data && data.user ? data.user : data || {};
                if (!u || (!u.email && !u.name && !u.meaningful_name)) {
                  try {
                    const meR = await fetch("/api/auth/me", { credentials: "include" });
                    if (meR.ok) {
                      const me = await meR.json();
                      u = me && me.user ? me.user : me || u;
                    }
                  } catch {
                    // noop
                  }
                }

                onLoggedIn({
                  fullName: u?.name || u?.meaningful_name || "User",
                  email: u?.email || "",
                  picture: u?.picture || "",
                  sub: u?.sub,
                });
              } catch (e) {
                console.error(e);
                alert("No se pudo iniciar sesión con Google.");
              }
            },
          });

          const el = document.getElementById("googleBtn");
          if (el) {
            el.innerHTML = "";
            window.google.accounts.id.renderButton(el, {
              theme: "outline",
              size: "large",
              shape: "pill",
              text: "continue_with",
              width: 340,
            });
          }
        }
      } catch (e) {
        console.error(e);
        setReady(false);
      }
    })();
  }, [open, googleClientId, onLoggedIn]);

  const sendMagicLink = async () => {
    const em = String(email || "").trim().toLowerCase();
    if (!em || !em.includes("@")) {
      setEmailError("Ingresá un email válido.");
      return;
    }
    setEmailError("");
    setEmailSent(false);
    setEmailSending(true);
    try {
      const r = await fetch("/api/auth/email/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ email: em }),
      });
      const data = await readJsonOrText(r);
      if (!r.ok) throw new Error((data && data.detail) || "No se pudo enviar el link");

      setEmailSent(true);
    } catch (e) {
      console.error(e);
      setEmailError(e?.message ? String(e.message) : "No se pudo enviar el link. Probá de nuevo en un minuto.");
    } finally {
      setEmailSending(false);
    }
  };

  if (!open) return null;
  const showGoogleTab = allowGoogleLogin;
  const showEmailTab = allowMagicLinkLogin;

  return (
    <div className="fixed inset-0 z-[100] bg-black/80 backdrop-blur-sm flex items-center justify-center p-6">
      <div className={`w-full max-w-md p-8 rounded-[2.5rem] ${UI.card} text-white`}>
        <div className="flex items-start justify-between gap-4 mb-6">
          <div>
            <div className="text-[9px] font-black uppercase tracking-widest text-neutral-500">Login requerido</div>
            <div className="text-2xl font-black uppercase italic">Ingresar</div>
            <div className="text-[11px] text-neutral-400 mt-2">Iniciá sesión para comprar o gestionar eventos.</div>
          </div>

          <button onClick={onClose} className="p-2 rounded-2xl hover:bg-white/5 transition-all">
            <X />
          </button>
        </div>

        <div className="flex gap-2 mb-5">
          {showGoogleTab && (
            <button
            onClick={() => {
              if (tab === "google" && googleClientId && window.google?.accounts?.id) {
                try {
                  window.google.accounts.id.prompt();
                } catch {
                  // noop
                }
              }
              setTab("google");
            }}
            className={`flex-1 py-2 rounded-2xl text-[10px] font-black uppercase tracking-widest border transition-all ${
              tab === "google"
                ? "bg-white/10 border-white/20"
                : "bg-white/5 hover:bg-white/10 border-white/10"
            }`}
          >
            Google
          </button>
          )}
          {showEmailTab && (
            <button
            onClick={() => setTab("email")}
            className={`flex-1 py-2 rounded-2xl text-[10px] font-black uppercase tracking-widest border transition-all ${
              tab === "email"
                ? "bg-white/10 border-white/20"
                : "bg-white/5 hover:bg-white/10 border-white/10"
            }`}
          >
            Email
          </button>
          )}
        </div>

        <div className="space-y-4">
          {showGoogleTab && tab === "google" && (
            <>
              <div className="w-full flex justify-center">
                <div id="googleBtn" className="min-h-[44px]" />
              </div>

              <button
                type="button"
                onClick={() => {
                  if (googleClientId && window.google?.accounts?.id) {
                    try {
                      window.google.accounts.id.prompt();
                    } catch (e) {
                      console.error(e);
                      alert("No se pudo abrir Google en este navegador.");
                    }
                  }
                }}
                disabled={!googleClientId || !window.google?.accounts?.id}
                className={`w-full py-3 rounded-2xl border text-[10px] font-black uppercase tracking-widest transition-all ${
                  !googleClientId || !window.google?.accounts?.id
                    ? "bg-white/5 border-white/10 opacity-70"
                    : "bg-white/10 hover:bg-white/15 border-white/20"
                }`}
              >
                Continuar con Google
              </button>

              {!googleClientId && (
                <div className="text-[11px] text-neutral-400 text-center">
                  Falta configurar <span className="text-white/90 font-bold">GOOGLE_CLIENT_ID</span> en el backend.
                </div>
              )}

              {googleClientId && !ready && <div className="text-[11px] text-neutral-400 text-center">Cargando Google…</div>}
            </>
          )}

          {showEmailTab && tab === "email" && (
            <>
              <div className="space-y-2">
                <div className="text-[10px] font-black uppercase tracking-widest text-neutral-400">Magic link</div>

                <div className="flex gap-2">
                  <div className="flex-1">
                    <input
                      value={email}
                      onChange={(e) => {
                        setEmail(e.target.value);
                        setEmailError("");
                        setEmailSent(false);
                      }}
                      placeholder="tu@email.com"
                      className="w-full px-4 py-3 rounded-2xl bg-white/5 border border-white/10 focus:outline-none focus:ring-2 focus:ring-indigo-500 text-sm"
                      autoComplete="email"
                      inputMode="email"
                    />
                  </div>

                  <button
                    onClick={sendMagicLink}
                    disabled={emailSending}
                    className={`px-4 py-3 rounded-2xl text-[10px] font-black uppercase tracking-widest border transition-all flex items-center gap-2 ${
                      emailSending
                        ? "bg-white/5 border-white/10 opacity-70"
                        : "bg-indigo-600 hover:bg-indigo-500 border-white/10"
                    }`}
                  >
                    {emailSending ? <Loader2 className="animate-spin" size={16} /> : <Mail size={16} />}
                    Enviar
                  </button>
                </div>

                {!!emailError && <div className="text-[11px] text-red-300">{emailError}</div>}

                {emailSent && (
                  <div className="text-[11px] text-emerald-300">
                    Listo ✅ Te mandamos un link. Abrilo desde tu correo para iniciar sesión.
                  </div>
                )}

                <div className="text-[11px] text-neutral-400">
                  El link vence en pocos minutos. Si no llega, revisá spam/promociones.
                </div>
              </div>
            </>
          )}

          <button
            onClick={onClose}
            className="w-full py-3 rounded-2xl bg-white/5 hover:bg-white/10 border border-white/10 text-[10px] font-black uppercase tracking-widest transition-all"
          >
            Cancelar
          </button>
        </div>
      </div>
    </div>
  );
}
