"use client";
import { CheckCircle2, Download, LogOut, MessageCircleQuestion, Moon, Search, Sun } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import Logo from "@/components/Logo";
import { api } from "@/lib/api";
import { t } from "@/lib/i18n";
import { useUI } from "@/lib/store";

export default function TopBar({ title, sessionId, onAsk }: {
  title?: string; sessionId?: string; onAsk?: () => void;
}) {
  const { theme, toggleTheme, lang, setLang, user, logout } = useUI();
  const tr = t(lang);
  const pathname = usePathname() ?? "/";
  const [exportOpen, setExportOpen] = useState(false);
  const urls = sessionId ? api.exportUrls(sessionId) : null;

  const navItems = [
    { label: tr.nav.upload, href: "/", active: pathname === "/" },
    { label: tr.nav.analysis, href: sessionId ? `/analyze/${sessionId}` : "/", active: pathname.startsWith("/analyze") },
    { label: tr.nav.report, href: sessionId ? `/report/${sessionId}` : "/", active: pathname.startsWith("/report") },
  ];

  return (
    <header className="glass sticky top-0 z-40 border-b border-line">
      <div className="mx-auto flex max-w-[1280px] flex-wrap items-center gap-3.5 px-4 py-2.5 sm:px-6 lg:px-10">
        <Link href="/" aria-label="Verolytics home" className="flex shrink-0 items-center gap-2.5 text-fg">
          <Logo size={30} />
          <span className="hidden font-heading text-[19px] font-semibold tracking-[-0.02em] sm:inline">
            {tr.appName}
          </span>
        </Link>

        {/* nav pills */}
        <nav className="hidden shrink-0 items-center gap-[3px] rounded-full border border-line bg-[var(--bg-2)] p-[3px] md:flex">
          {navItems.map((n) => (
            <Link key={n.label} href={n.href}
              className={`rounded-full px-3.5 py-1.5 text-[13.5px] font-medium transition ${
                n.active ? "bg-[var(--bg-3)] text-fg shadow-sm" : "text-[var(--fg-2)] hover:text-fg"}`}>
              {n.label}
            </Link>
          ))}
        </nav>

        {/* command / search */}
        <button aria-label={tr.search}
          onClick={() => window.dispatchEvent(new CustomEvent("verolytics:command-palette"))}
          className="flex h-10 min-w-[160px] flex-1 items-center gap-2.5 rounded-xl border border-line bg-[var(--bg-1)] px-3 text-[var(--fg-2)] transition hover:border-line-strong">
          <Search size={17} />
          <span className="flex-1 truncate text-start text-sm">{title ? `/ ${title}` : tr.search}</span>
          <kbd className="rounded-md border border-line bg-[var(--bg-3)] px-1.5 py-0.5 font-mono text-[11px] text-muted">⌘K</kbd>
        </button>

        <div className="flex shrink-0 items-center gap-2">
          {title && (
            <span className="hidden items-center gap-1.5 rounded-full border px-2.5 text-[12.5px] font-semibold lg:inline-flex"
              style={{ height: 32, background: "var(--verified-bg)", borderColor: "var(--verified-line)", color: "var(--verified-ink)" }}>
              <CheckCircle2 size={14} /> {tr.verified}
            </span>
          )}

          {urls && (
            <div className="relative">
              <button onClick={() => setExportOpen(!exportOpen)}
                className="btn-grad flex h-9 items-center gap-1.5 rounded-xl px-4 text-[13.5px] font-semibold">
                <Download size={15} /> <span className="hidden sm:inline">{tr.export}</span>
              </button>
              <AnimatePresence>
                {exportOpen && (
                  <motion.div initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: -6 }}
                    className="card absolute end-0 mt-2 w-56 overflow-hidden p-1.5 text-sm">
                    {[
                      [tr.pdf, urls.pdf], [tr.html, urls.html], [tr.pptx, urls.pptx],
                      [tr.slides, urls.slides], [tr.cleanedCsv, urls.cleanedCsv],
                    ].map(([label, href]) => (
                      <a key={href} href={href} target="_blank" rel="noreferrer"
                        onClick={() => setExportOpen(false)}
                        className="block rounded-lg px-3 py-2 text-fg transition hover:bg-violet-500/10">
                        {label}
                      </a>
                    ))}
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          )}

          {onAsk && (
            <button onClick={onAsk}
              className="hidden h-9 items-center gap-1.5 rounded-xl border border-line bg-[var(--bg-2)] px-3.5 text-[13.5px] font-semibold transition hover:border-line-strong sm:flex">
              <MessageCircleQuestion size={15} /> <span className="hidden md:inline">{tr.ask}</span>
            </button>
          )}

          <button aria-label="language" title="Language" onClick={() => setLang(lang === "en" ? "ar" : "en")}
            className="grid h-9 place-items-center rounded-xl border border-line bg-[var(--bg-2)] px-3 text-[13px] font-semibold transition hover:border-line-strong">
            {lang === "en" ? "ع" : "EN"}
          </button>
          <button aria-label="theme" title="Theme" onClick={toggleTheme}
            className="grid h-9 w-9 place-items-center rounded-xl border border-line bg-[var(--bg-2)] transition hover:border-line-strong">
            {theme === "light" ? <Moon size={17} /> : <Sun size={17} />}
          </button>

          {user ? (
            <button aria-label="sign out" title={user.email}
              onClick={async () => { await api.logout().catch(() => {}); logout(); }}
              className="grid h-9 w-9 place-items-center rounded-xl border border-line bg-[var(--bg-2)] transition hover:border-line-strong">
              <LogOut size={16} />
            </button>
          ) : (
            <button onClick={() => window.dispatchEvent(new CustomEvent("verolytics:open-auth"))}
              className="h-9 rounded-xl px-4 text-[13.5px] font-semibold transition hover:brightness-90 active:translate-y-px"
              style={{ background: "var(--fg)", color: "var(--bg)" }}>
              {tr.auth.signIn}
            </button>
          )}
        </div>
      </div>
    </header>
  );
}
