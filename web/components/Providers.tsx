"use client";
import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import AuthModal from "@/components/AuthModal";
import CommandPalette from "@/components/CommandPalette";
import { useUI } from "@/lib/store";

/* Applies theme class + text direction to <html>, provides toasts. */

interface Toast { id: number; text: string; kind: "ok" | "err" }
const ToastCtx = createContext<(text: string, kind?: "ok" | "err") => void>(() => {});
export const useToast = () => useContext(ToastCtx);

export default function Providers({ children }: { children: React.ReactNode }) {
  const { theme, lang } = useUI();
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [mounted, setMounted] = useState(false);

  useEffect(() => setMounted(true), []);
  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
    document.documentElement.dir = lang === "ar" ? "rtl" : "ltr";
    document.documentElement.lang = lang;
  }, [theme, lang]);

  const push = useCallback((text: string, kind: "ok" | "err" = "ok") => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, text, kind }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 3500);
  }, []);

  // avoid hydration mismatch from persisted store
  if (!mounted) return <div className="min-h-screen" />;

  return (
    <ToastCtx.Provider value={push}>
      {children}
      <CommandPalette />
      <AuthModal />
      <div className="fixed bottom-5 left-1/2 z-[70] -translate-x-1/2 space-y-2">
        <AnimatePresence>
          {toasts.map((t) => (
            <motion.div key={t.id}
              initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: 16 }}
              className={`card px-4 py-2.5 text-sm ${
                t.kind === "err" ? "border-rose-400/40 text-rose-400"
                                 : "text-fg"}`}>
              {t.text}
            </motion.div>
          ))}
        </AnimatePresence>
      </div>
    </ToastCtx.Provider>
  );
}
