"use client";
import { AnimatePresence, motion } from "framer-motion";
import { Send, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api, type ChartMeta } from "@/lib/api";
import { t } from "@/lib/i18n";
import { useUI } from "@/lib/store";
import RemoteChart from "./Plot";

interface Msg {
  role: "user" | "agent";
  text: string;
  charts?: ChartMeta[];
  stats?: { label: string; value: number }[];
}

const SCENARIO_RE = /^(what if|what happens|ماذا لو|ماذا يحدث)/i;

export default function ChatDrawer({ sessionId, open, onClose }: {
  sessionId: string; open: boolean; onClose: () => void;
}) {
  const lang = useUI((s) => s.lang);
  const tr = t(lang);
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const bottom = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (open) api.suggestions(sessionId).then((r) => setSuggestions(r.suggestions)).catch(() => {});
  }, [open, sessionId]);
  useEffect(() => { bottom.current?.scrollIntoView({ behavior: "smooth" }); }, [messages, busy]);
  useEffect(() => {
    // persist chat per session
    const saved = sessionStorage.getItem(`chat-${sessionId}`);
    if (saved) setMessages(JSON.parse(saved));
  }, [sessionId]);
  useEffect(() => {
    sessionStorage.setItem(`chat-${sessionId}`, JSON.stringify(messages));
  }, [messages, sessionId]);

  const send = async (text: string) => {
    if (!text.trim() || busy) return;
    setMessages((m) => [...m, { role: "user", text }]);
    setInput("");
    setBusy(true);
    try {
      if (SCENARIO_RE.test(text.trim())) {
        const r = await api.scenario(sessionId, text.trim());
        const stats = [
          { label: tr.expected, value: r.expected_outcome },
          { label: tr.bestCase, value: r.best_case },
          { label: tr.worstCase, value: r.worst_case },
          { label: tr.baseline, value: r.baseline },
        ].filter((s): s is { label: string; value: number } => typeof s.value === "number");
        setMessages((m) => [...m, { role: "agent", text: r.answer, charts: r.charts, stats }]);
      } else {
        const r = await api.chat(sessionId, text.trim(), lang);
        setMessages((m) => [...m, { role: "agent", text: r.answer }]);
      }
    } catch (e) {
      setMessages((m) => [...m, { role: "agent", text: `⚠️ ${String((e as Error).message ?? e)}` }]);
    } finally {
      setBusy(false);
    }
  };

  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div className="fixed inset-0 z-40 bg-black/30 backdrop-blur-sm"
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            onClick={onClose} />
          <motion.aside
            initial={{ x: "100%" }} animate={{ x: 0 }} exit={{ x: "100%" }}
            transition={{ type: "spring", damping: 28, stiffness: 260 }}
            className="fixed end-0 top-0 z-50 flex h-full w-full max-w-lg flex-col border-s border-line bg-bg shadow-lift"
          >
            <div className="flex items-center justify-between gap-3 border-b border-line px-5 py-4">
              <div>
                <h3 className="font-heading font-semibold">{tr.chatTitle}</h3>
                <p className="text-xs text-dim">{tr.chatHint}</p>
              </div>
              <button onClick={onClose} aria-label="close"
                className="rounded-lg p-2 text-dim transition hover:bg-indigo-500/10 hover:text-fg"><X size={18} /></button>
            </div>

            <div className="flex-1 space-y-4 overflow-y-auto px-5 py-4">
              {messages.length === 0 && (
                <div className="flex flex-wrap gap-2 pt-2">
                  {suggestions.map((s) => (
                    <button key={s} className="chip" onClick={() => send(s)}>{s}</button>
                  ))}
                </div>
              )}
              {messages.map((m, i) => (
                <div key={i} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
                  <div className={`max-w-[88%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed ${
                    m.role === "user"
                      ? "rounded-br-sm bg-grad-iris text-white"
                      : "card rounded-bl-sm"}`}>
                    <div className="whitespace-pre-wrap">{m.text}</div>
                    {m.stats && m.stats.length > 0 && (
                      <div className="mt-3 grid grid-cols-2 gap-2">
                        {m.stats.map((s) => (
                          <div key={s.label} className="rounded-lg border border-line bg-surface p-2 text-center">
                            <div className="font-mono text-base font-semibold text-indigo-500 dark:text-indigo-300">
                              {s.value.toLocaleString()}
                            </div>
                            <div className="text-[11px] text-dim">{s.label}</div>
                          </div>
                        ))}
                      </div>
                    )}
                    {m.charts?.map((c) => (
                      <div key={c.name} className="mt-3 overflow-hidden rounded-lg border border-line bg-surface">
                        <RemoteChart sessionId={sessionId} name={c.name} height={240} />
                      </div>
                    ))}
                  </div>
                </div>
              ))}
              {busy && (
                <div className="flex justify-start">
                  <div className="typing card rounded-2xl rounded-bl-sm px-4 py-3">
                    <span /> <span /> <span />
                  </div>
                </div>
              )}
              <div ref={bottom} />
            </div>

            <form className="flex gap-2 border-t border-line p-4"
              onSubmit={(e) => { e.preventDefault(); send(input); }}>
              <input value={input} onChange={(e) => setInput(e.target.value)}
                placeholder={tr.chatPh} disabled={busy}
                className="flex-1 rounded-xl border border-line-strong bg-surface px-4 py-2.5 text-sm text-fg outline-none transition focus:border-indigo-500" />
              <button type="submit" disabled={busy || !input.trim()} aria-label="send"
                className="btn-grad grid place-items-center rounded-xl px-4 disabled:opacity-40">
                <Send size={16} />
              </button>
            </form>
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  );
}
