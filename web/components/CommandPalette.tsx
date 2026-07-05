"use client";
import { AnimatePresence, motion } from "framer-motion";
import {
  ArrowRight, Clock, CornerDownLeft, Download, FileDown, FileText, Home, Languages,
  MessageCircleQuestion, Moon, Presentation, Search, Sun, Table2, TrendingUp,
} from "lucide-react";
import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { LucideIcon } from "lucide-react";
import { api, type SessionInfo } from "@/lib/api";
import { t } from "@/lib/i18n";
import { useUI } from "@/lib/store";

/** Global ⌘K / Ctrl-K command palette: fuzzy search over context-aware actions
 *  (navigation, appearance, per-report export/ask, recent sessions). */
interface Cmd {
  id: string;
  label: string;
  section: string;
  icon: LucideIcon;
  keywords?: string;
  run: () => void;
}

// session id out of /report/<id> or /analyze/<id>
function sessionFromPath(path: string | null): { id: string; kind: "report" | "analyze" } | null {
  const m = /\/(report|analyze)\/([^/?#]+)/.exec(path ?? "");
  return m ? { kind: m[1] as "report" | "analyze", id: m[2] } : null;
}

export default function CommandPalette() {
  const router = useRouter();
  const pathname = usePathname();
  const { theme, toggleTheme, lang, setLang } = useUI();
  const tr = t(lang);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const [recent, setRecent] = useState<SessionInfo[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  // open via ⌘K / Ctrl-K (toggle) or a custom event from anywhere in the app
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((o) => !o);
      }
    };
    const onOpen = () => setOpen(true);
    window.addEventListener("keydown", onKey);
    window.addEventListener("verolytics:command-palette", onOpen);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("verolytics:command-palette", onOpen);
    };
  }, []);

  // reset + focus on open; lazily load recent sessions
  useEffect(() => {
    if (!open) return;
    setQuery("");
    setActive(0);
    const id = requestAnimationFrame(() => inputRef.current?.focus());
    api.sessions().then((s) => setRecent(s.slice(0, 5))).catch(() => {});
    return () => cancelAnimationFrame(id);
  }, [open]);

  const go = useCallback((fn: () => void) => { setOpen(false); fn(); }, []);

  const commands = useMemo<Cmd[]>(() => {
    const c = tr.cmd;
    const list: Cmd[] = [
      { id: "home", section: c.secNav, icon: Home, label: c.home, keywords: "upload new home start",
        run: () => go(() => router.push("/")) },
      { id: "theme", section: c.secAppearance, icon: theme === "light" ? Moon : Sun,
        label: c.theme, keywords: "dark light mode", run: () => go(toggleTheme) },
      { id: "lang", section: c.secAppearance, icon: Languages, label: c.language,
        keywords: "arabic english عربي rtl", run: () => go(() => setLang(lang === "en" ? "ar" : "en")) },
    ];

    const ctx = sessionFromPath(pathname);
    if (ctx) {
      const urls = api.exportUrls(ctx.id);
      const openTab = (u: string) => go(() => window.open(u, "_blank", "noopener"));
      if (ctx.kind === "analyze") {
        list.unshift({ id: "open-report", section: c.secReport, icon: FileText, label: c.openReport,
          keywords: "report result", run: () => go(() => router.push(`/report/${ctx.id}`)) });
      } else {
        list.unshift(
          { id: "ask", section: c.secReport, icon: MessageCircleQuestion, label: c.ask,
            keywords: "chat question scenario what if",
            run: () => go(() => window.dispatchEvent(new CustomEvent("verolytics:open-chat"))) },
          { id: "predict", section: c.secReport, icon: TrendingUp, label: c.predict,
            keywords: "forecast ml machine learning future values",
            run: () => go(() => document.getElementById("predict")?.scrollIntoView({ behavior: "smooth" })) },
          { id: "pdf", section: c.secReport, icon: FileDown, label: c.exportPdf,
            keywords: "export download", run: () => openTab(urls.pdf) },
          { id: "pptx", section: c.secReport, icon: Presentation, label: c.exportPptx,
            keywords: "export powerpoint deck", run: () => openTab(urls.pptx) },
          { id: "slides", section: c.secReport, icon: Presentation, label: c.exportSlides,
            keywords: "export web slides reveal", run: () => openTab(urls.slides) },
          { id: "csv", section: c.secReport, icon: Table2, label: c.exportCsv,
            keywords: "export cleaned data csv", run: () => openTab(urls.cleanedCsv) },
          { id: "html", section: c.secReport, icon: Download, label: c.openHtml,
            keywords: "export html", run: () => openTab(urls.html) },
        );
      }
    }

    for (const s of recent) {
      const done = s.status === "done";
      list.push({
        id: `recent-${s.session_id}`, section: c.secRecent, icon: Clock,
        label: s.filename, keywords: `${s.status} session`,
        run: () => go(() => router.push(`${done ? "/report" : "/analyze"}/${s.session_id}`)),
      });
    }
    return list;
  }, [tr, theme, lang, pathname, recent, router, toggleTheme, setLang, go]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return commands;
    return commands.filter((cmd) =>
      `${cmd.label} ${cmd.keywords ?? ""} ${cmd.section}`.toLowerCase().includes(q));
  }, [commands, query]);

  useEffect(() => { setActive((a) => Math.min(a, Math.max(0, filtered.length - 1))); }, [filtered.length]);

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") { setOpen(false); return; }
    if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => (a + 1) % filtered.length); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => (a - 1 + filtered.length) % filtered.length); }
    else if (e.key === "Enter") { e.preventDefault(); filtered[active]?.run(); }
  };

  // keep the active row in view
  useEffect(() => {
    listRef.current?.querySelector<HTMLElement>(`[data-idx="${active}"]`)
      ?.scrollIntoView({ block: "nearest" });
  }, [active]);

  // section order is the order commands first appear
  const sections = filtered.reduce<Record<string, Cmd[]>>((acc, cmd) => {
    (acc[cmd.section] ||= []).push(cmd);
    return acc;
  }, {});
  let flatIdx = -1;

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className="fixed inset-0 z-[90] flex items-start justify-center bg-black/30 p-4 pt-[12vh] backdrop-blur-sm"
          initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
          onClick={() => setOpen(false)}
        >
          <motion.div
            initial={{ opacity: 0, y: -12, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -12, scale: 0.98 }} transition={{ type: "spring", damping: 26, stiffness: 320 }}
            className="card-raised w-full max-w-xl overflow-hidden"
            onClick={(e) => e.stopPropagation()} onKeyDown={onKeyDown}
          >
            <div className="flex items-center gap-3 border-b border-line px-4 py-3.5">
              <Search size={18} className="text-dim" />
              <input
                ref={inputRef} value={query} onChange={(e) => setQuery(e.target.value)}
                placeholder={tr.cmd.placeholder}
                className="w-full bg-transparent text-[15px] text-fg outline-none placeholder:text-dim"
              />
              <kbd className="pill px-2 py-0.5 font-mono text-[11px] text-dim">esc</kbd>
            </div>

            <div ref={listRef} className="max-h-[52vh] overflow-y-auto p-2">
              {filtered.length === 0 && (
                <div className="px-3 py-8 text-center text-sm text-dim">{tr.cmd.empty}</div>
              )}
              {Object.entries(sections).map(([section, cmds]) => (
                <div key={section} className="mb-1">
                  <div className="px-3 pb-1 pt-2 text-[11px] font-semibold uppercase tracking-wider text-dim">
                    {section}
                  </div>
                  {cmds.map((cmd) => {
                    flatIdx += 1;
                    const idx = flatIdx;
                    const Icon = cmd.icon;
                    const selected = idx === active;
                    return (
                      <button
                        key={cmd.id} data-idx={idx}
                        onMouseMove={() => setActive(idx)} onClick={() => cmd.run()}
                        className={`flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-start text-sm transition ${
                          selected ? "bg-accent text-white" : "text-fg"}`}
                      >
                        <Icon size={16} className={selected ? "text-white" : "text-accent"} />
                        <span className="flex-1 truncate">{cmd.label}</span>
                        {selected && <ArrowRight size={14} className="opacity-80" />}
                      </button>
                    );
                  })}
                </div>
              ))}
            </div>

            <div className="flex items-center gap-4 border-t border-line px-4 py-2.5 text-[11px] text-dim">
              <span className="flex items-center gap-1"><kbd className="font-mono">↑↓</kbd> {tr.cmd.select}</span>
              <span className="flex items-center gap-1"><CornerDownLeft size={12} /> {tr.cmd.enter}</span>
              <span className="ms-auto flex items-center gap-1"><kbd className="font-mono">esc</kbd> {tr.cmd.esc}</span>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
