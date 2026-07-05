"use client";
import { AnimatePresence, motion } from "framer-motion";
import { Loader2, Lock, Mail, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { t } from "@/lib/i18n";
import { useUI } from "@/lib/store";

/** Global sign-in / register modal. Opens on the "verolytics:open-auth" event. */
export default function AuthModal() {
  const { lang, setAuth } = useUI();
  const tr = t(lang).auth;
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<"in" | "up">("in");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const emailRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const onOpen = () => { setOpen(true); setError(null); };
    window.addEventListener("verolytics:open-auth", onOpen);
    return () => window.removeEventListener("verolytics:open-auth", onOpen);
  }, []);
  useEffect(() => { if (open) requestAnimationFrame(() => emailRef.current?.focus()); }, [open]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (busy) return;
    setBusy(true); setError(null);
    try {
      const res = mode === "in"
        ? await api.login(email.trim(), password)
        : await api.register(email.trim(), password);
      setAuth(res.token, res.user);
      setOpen(false); setPassword("");
    } catch (err) {
      setError(String((err as Error).message ?? err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className="fixed inset-0 z-[95] grid place-items-center bg-black/40 p-4 backdrop-blur-sm"
          initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
          onClick={() => setOpen(false)}
        >
          <motion.div
            initial={{ opacity: 0, y: 14, scale: 0.97 }} animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 14, scale: 0.97 }} transition={{ type: "spring", damping: 26, stiffness: 320 }}
            className="card-raised w-full max-w-sm p-7" onClick={(e) => e.stopPropagation()}
          >
            <div className="mb-1 flex items-start justify-between">
              <h2 className="font-heading text-xl font-semibold">
                {mode === "in" ? tr.titleIn : tr.titleUp}
              </h2>
              <button onClick={() => setOpen(false)} aria-label="close"
                className="rounded-lg p-1 text-dim transition hover:text-fg"><X size={18} /></button>
            </div>
            <p className="mb-5 text-sm text-muted">{mode === "in" ? tr.subIn : tr.subUp}</p>

            <form onSubmit={submit} className="space-y-3">
              <label className="flex items-center gap-2 rounded-xl border border-line-strong bg-surface px-3 py-2.5">
                <Mail size={16} className="text-dim" />
                <input ref={emailRef} type="email" required value={email} dir="ltr"
                  onChange={(e) => setEmail(e.target.value)} placeholder={tr.email}
                  className="w-full bg-transparent text-sm text-fg outline-none placeholder:text-dim" />
              </label>
              <label className="flex items-center gap-2 rounded-xl border border-line-strong bg-surface px-3 py-2.5">
                <Lock size={16} className="text-dim" />
                <input type="password" required minLength={8} value={password} dir="ltr"
                  onChange={(e) => setPassword(e.target.value)} placeholder={tr.password}
                  className="w-full bg-transparent text-sm text-fg outline-none placeholder:text-dim" />
              </label>
              {mode === "up" && <p className="text-xs text-dim">{tr.passwordHint}</p>}
              {error && (
                <p className="rounded-lg border border-rose-400/40 bg-rose-400/10 px-3 py-2 text-xs text-rose-400">
                  {error}
                </p>
              )}
              <button type="submit" disabled={busy}
                className="btn-grad flex w-full items-center justify-center gap-2 rounded-xl py-3 font-semibold disabled:opacity-50">
                {busy && <Loader2 size={16} className="animate-spin" />}
                {mode === "in" ? tr.submitIn : tr.submitUp}
              </button>
            </form>

            <button onClick={() => { setMode(mode === "in" ? "up" : "in"); setError(null); }}
              className="mt-4 w-full text-center text-xs text-accent hover:underline">
              {mode === "in" ? tr.toUp : tr.toIn}
            </button>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
