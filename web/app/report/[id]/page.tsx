"use client";
import { AnimatePresence, motion } from "framer-motion";
import {
  AlertTriangle, BadgeCheck, ChevronDown, Maximize2, MessageCircleQuestion, Sparkles, X,
} from "lucide-react";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import ChatDrawer from "@/components/ChatDrawer";
import KpiCard from "@/components/KpiCard";
import RemoteChart from "@/components/Plot";
import PredictPanel from "@/components/PredictPanel";
import TopBar from "@/components/TopBar";
import { api, type Quality, type Report } from "@/lib/api";
import { t } from "@/lib/i18n";
import { useUI } from "@/lib/store";

const TAG_COLORS: Record<string, string> = {
  one_time_event: "bg-indigo-500/12 text-indigo-400 border border-indigo-500/30",
  emerging_trend: "bg-mint-500/12 text-mint-500 border border-mint-500/30",
  seasonal_pattern: "bg-amber-400/12 text-amber-400 border border-amber-400/30",
  data_error: "bg-rose-400/12 text-rose-400 border border-rose-400/30",
};

function Confetti() {
  const colors = ["#7c3aed", "#06b6d4", "#d946ef", "#10b981", "#f59e0b"];
  return (
    <>
      {Array.from({ length: 36 }).map((_, i) => (
        <span key={i} className="confetti-piece"
          style={{
            left: `${(i * 137) % 100}%`,
            background: colors[i % colors.length],
            animationDelay: `${(i % 12) * 0.12}s`,
            borderRadius: i % 2 ? "50%" : "2px",
          }} />
      ))}
    </>
  );
}

function Bar({ label, value }: { label: string; value: number }) {
  const color = value >= 85 ? "bg-mint-500" : value >= 60 ? "bg-amber-400" : "bg-rose-400";
  return (
    <div>
      <div className="mb-1 flex justify-between text-xs text-dim">
        <span>{label}</span><span className="font-mono">{value}%</span>
      </div>
      <div className="h-2 rounded-full bg-line">
        <motion.div initial={{ width: 0 }} whileInView={{ width: `${value}%` }}
          viewport={{ once: true }} transition={{ duration: 0.8 }}
          className={`h-2 rounded-full ${color}`} />
      </div>
    </div>
  );
}

type ChartKind = "bar" | "scatter" | "area" | null;

function ChartWithSwitcher({ sessionId, name, onZoom }: {
  sessionId: string; name: string; onZoom?: (n: string) => void;
}) {
  const [kind, setKind] = useState<ChartKind>(null);
  return (
    <div>
      <div className="mb-1 flex items-center justify-end gap-1">
        {([null, "bar", "scatter", "area"] as ChartKind[]).map((k) => (
          <button key={String(k)} onClick={() => setKind(k)}
            className={`rounded-md px-2 py-0.5 font-mono text-[11px] transition ${kind === k
              ? "btn-grad" : "bg-surface text-dim hover:text-fg"}`}>
            {k === null ? "auto" : k === "scatter" ? "line" : k}
          </button>
        ))}
        {onZoom && (
          <button onClick={() => onZoom(name)} aria-label="expand chart"
            className="ms-1 grid h-6 w-6 place-items-center rounded-md bg-surface text-dim transition hover:text-fg">
            <Maximize2 size={12} />
          </button>
        )}
      </div>
      <RemoteChart sessionId={sessionId} name={name} typeOverride={kind} />
    </div>
  );
}

export default function ReportPage() {
  const { id } = useParams<{ id: string }>();
  const { lang, setLang, confetti } = useUI();
  const tr = t(lang);
  const [report, setReport] = useState<Report | null>(null);
  const [quality, setQuality] = useState<Quality | null>(null);
  const [chatOpen, setChatOpen] = useState(false);
  const [openCode, setOpenCode] = useState<number | null>(null);
  const [celebrate, setCelebrate] = useState(false);
  const [zoomChart, setZoomChart] = useState<string | null>(null);
  const [activeSection, setActiveSection] = useState("");

  useEffect(() => {
    api.report(id).then((r) => {
      setReport(r);
      if (r.language === "ar" || r.language === "en") setLang(r.language);
      if (confetti && !sessionStorage.getItem(`seen-${id}`)) {
        sessionStorage.setItem(`seen-${id}`, "1");
        setCelebrate(true);
        setTimeout(() => setCelebrate(false), 2600);
      }
    }).catch(() => {});
    api.quality(id).then(setQuality).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  // "Ask the data" from the global command palette opens the chat drawer
  useEffect(() => {
    const open = () => setChatOpen(true);
    window.addEventListener("verolytics:open-chat", open);
    return () => window.removeEventListener("verolytics:open-chat", open);
  }, []);

  const verification = report?.verification as { checked?: number; matched?: number; redacted?: boolean } | undefined;
  const chartNames = useMemo(() => new Set(report?.charts.map((c) => c.name)), [report]);

  // table-of-contents sections (only those that exist), for the storytelling nav
  const sections = useMemo(() => {
    if (!report) return [];
    return [
      report.executive_summary && { id: "summary", label: tr.executiveSummary },
      report.findings.length > 0 && { id: "findings", label: tr.findings },
      report.anomalies.length > 0 && { id: "anomalies", label: tr.anomalies },
      report.segments.length > 0 && { id: "segments", label: tr.segments },
      report.forecast && { id: "forecast", label: tr.forecast },
      { id: "predict", label: tr.predict.title },
      report.recommendations.length > 0 && { id: "recommendations", label: tr.recommendations },
      { id: "quality", label: tr.quality },
    ].filter(Boolean) as { id: string; label: string }[];
  }, [report, tr]);

  // highlight the section currently in view
  useEffect(() => {
    if (sections.length === 0) return;
    const obs = new IntersectionObserver(
      (entries) => {
        const vis = entries.filter((e) => e.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
        if (vis[0]) setActiveSection(vis[0].target.id);
      },
      { rootMargin: "-120px 0px -65% 0px" },
    );
    sections.forEach((s) => { const el = document.getElementById(s.id); if (el) obs.observe(el); });
    return () => obs.disconnect();
  }, [sections]);

  if (!report) {
    return (
      <main className="min-h-screen">
        <TopBar />
        <div className="mx-auto max-w-7xl space-y-6 px-4 py-8">
          <div className="skeleton h-9 w-1/2" />
          <div className="flex gap-4">{[1, 2, 3, 4].map((i) => <div key={i} className="skeleton h-28 flex-1" />)}</div>
          <div className="skeleton h-96 w-full" />
        </div>
      </main>
    );
  }

  return (
    <main className="min-h-screen pb-24">
      {celebrate && <Confetti />}
      <TopBar title={report.title} sessionId={id} onAsk={() => setChatOpen(true)} />

      {/* storytelling section nav — sticky table of contents */}
      <nav className="glass sticky top-[57px] z-30 border-b border-line">
        <div className="mx-auto flex max-w-7xl gap-1 overflow-x-auto px-4 py-2">
          {sections.map((s) => (
            <button key={s.id}
              onClick={() => document.getElementById(s.id)?.scrollIntoView({ behavior: "smooth" })}
              className={`whitespace-nowrap rounded-full px-3 py-1.5 text-xs font-medium transition ${
                activeSection === s.id ? "bg-accent text-white" : "text-dim hover:text-fg"}`}>
              {s.label}
            </button>
          ))}
        </div>
      </nav>

      <div className="mx-auto max-w-7xl px-4 py-8">
        {/* header */}
        <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}>
          <h1 className="font-heading text-2xl font-semibold tracking-tight sm:text-3xl">{report.title}</h1>
          <div className="mt-3 flex flex-wrap items-center gap-2 text-sm">
            {verification?.redacted ? (
              <span className="flex items-center gap-1.5 rounded-full border border-amber-400/30 bg-amber-400/10 px-3 py-1 font-mono text-xs font-medium text-amber-400">
                <AlertTriangle size={13} /> {tr.redactedBadge}
              </span>
            ) : (
              <span className="flex items-center gap-1.5 rounded-full border border-mint-500/30 bg-mint-500/10 px-3 py-1 font-mono text-xs font-medium text-mint-500">
                <span className="h-[7px] w-[7px] rounded-full bg-mint-500 shadow-[0_0_8px_#34d399]" />
                {verification?.matched}/{verification?.checked} {tr.verifiedBadge}
              </span>
            )}
          </div>
        </motion.div>

        {/* KPI row */}
        {report.kpis.length > 0 && (
          <div className="mt-6 flex gap-4 overflow-x-auto pb-2 sm:grid sm:grid-cols-2 lg:grid-cols-4">
            {report.kpis.map((k, i) => <KpiCard key={i} kpi={k} index={i} />)}
          </div>
        )}

        {/* executive summary */}
        <motion.section id="summary" initial={{ opacity: 0 }} whileInView={{ opacity: 1 }} viewport={{ once: true }}
          className="card mt-8 scroll-mt-32 border-s-[3px] border-s-indigo-500 p-6">
          <h2 className="kicker mb-3 flex items-center gap-2">
            <Sparkles size={14} /> {tr.executiveSummary}
          </h2>
          <p className="text-[16.5px] leading-relaxed text-fg">{report.executive_summary}</p>
        </motion.section>

        {/* findings */}
        {report.findings.length > 0 && (
          <section id="findings" className="mt-12 scroll-mt-32">
            <h2 className="font-heading mb-4 text-xl font-bold">{tr.findings}</h2>
            <div className="space-y-6">
              {report.findings.map((f, i) => (
                <motion.article key={i} initial={{ opacity: 0, y: 16 }} whileInView={{ opacity: 1, y: 0 }}
                  viewport={{ once: true, margin: "-60px" }} transition={{ delay: (i % 3) * 0.1 }}
                  className="card p-6">
                  <h3 className="font-heading text-lg font-semibold">
                    <span className="text-pink-400">{i + 1}.</span> {f.title}
                  </h3>
                  {f.chart_name && chartNames.has(f.chart_name) && (
                    <div className="mt-4"><ChartWithSwitcher sessionId={id} name={f.chart_name} onZoom={setZoomChart} /></div>
                  )}
                  <p className="mt-3 text-sm leading-relaxed text-muted">{f.narrative}</p>
                  {f.code && (
                    <div className="mt-3">
                      <button onClick={() => setOpenCode(openCode === i ? null : i)}
                        className="flex items-center gap-1.5 font-mono text-xs font-medium text-indigo-500 dark:text-indigo-300">
                        <ChevronDown size={13} className={openCode === i ? "rotate-180" : ""} /> {"{ }"} {tr.showCode}
                      </button>
                      <AnimatePresence>
                        {openCode === i && (
                          <motion.pre initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }}
                            exit={{ height: 0, opacity: 0 }} dir="ltr"
                            className="code-surface mt-2 max-h-64 overflow-auto rounded-xl p-4 text-xs">
                            {f.code}
                          </motion.pre>
                        )}
                      </AnimatePresence>
                    </div>
                  )}
                </motion.article>
              ))}
            </div>
          </section>
        )}

        {/* anomalies */}
        {report.anomalies.length > 0 && (
          <section id="anomalies" className="mt-12 scroll-mt-32">
            <h2 className="font-heading mb-4 text-xl font-bold">🕵️ {tr.anomalies}</h2>
            <div className="grid gap-4 md:grid-cols-2">
              {report.anomalies.map((a, i) => (
                <motion.div key={i} initial={{ opacity: 0, y: 14 }} whileInView={{ opacity: 1, y: 0 }}
                  viewport={{ once: true }} className="card p-5">
                  <div className="flex items-center justify-between gap-2">
                    <h3 className="font-heading font-semibold">{a.title}</h3>
                    <span className={`rounded-full px-2.5 py-1 font-mono text-[11px] font-medium ${TAG_COLORS[a.tag] ?? TAG_COLORS.one_time_event}`}>
                      {tr.tagLabels[a.tag] ?? a.tag}
                    </span>
                  </div>
                  {a.chart_name && chartNames.has(a.chart_name) && (
                    <div className="mt-3"><RemoteChart sessionId={id} name={a.chart_name} height={260} /></div>
                  )}
                  <p className="mt-3 text-sm leading-relaxed text-muted">{a.narrative}</p>
                </motion.div>
              ))}
            </div>
          </section>
        )}

        {/* segments */}
        {report.segments.length > 0 && (
          <section id="segments" className="mt-12 scroll-mt-32">
            <h2 className="font-heading mb-4 text-xl font-bold">🧩 {tr.segments}</h2>
            <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
              {report.segments.map((s, i) => (
                <motion.div key={i} initial={{ opacity: 0, y: 14 }} whileInView={{ opacity: 1, y: 0 }}
                  viewport={{ once: true }} transition={{ delay: i * 0.08 }} className="card p-5">
                  <h3 className="font-heading font-semibold text-indigo-500 dark:text-indigo-300">{s.name}</h3>
                  <p className="mt-2 text-sm text-muted">{s.description}</p>
                  <p className="mt-3 rounded-xl border border-indigo-500/20 bg-indigo-500/8 p-3 text-sm text-fg">💡 {s.recommendation}</p>
                </motion.div>
              ))}
            </div>
          </section>
        )}

        {/* forecast */}
        {report.forecast && (
          <section id="forecast" className="mt-12 scroll-mt-32">
            <h2 className="font-heading mb-4 text-xl font-bold">📈 {tr.forecast}</h2>
            <div className="card p-6">
              {report.forecast.chart_name && chartNames.has(report.forecast.chart_name) && (
                <RemoteChart sessionId={id} name={report.forecast.chart_name} height={400} />
              )}
              <p className="mt-3 text-sm leading-relaxed text-muted">
                {report.forecast.narrative}
              </p>
              <div className="mt-4 flex flex-wrap items-center gap-4">
                {report.forecast.model_name && (
                  <span className="rounded-full border border-indigo-500/26 bg-indigo-500/12 px-3 py-1 font-mono text-xs font-medium text-indigo-500 dark:text-indigo-300">
                    {report.forecast.model_name}
                  </span>
                )}
                {typeof report.forecast.mape === "number" && (
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-dim">{tr.reliability}</span>
                    <div className="h-2 w-36 rounded-full bg-line">
                      <div className={`h-2 rounded-full ${report.forecast.mape <= 10 ? "bg-mint-500" : report.forecast.mape <= 25 ? "bg-amber-400" : "bg-rose-400"}`}
                        style={{ width: `${Math.max(8, 100 - report.forecast.mape * 2)}%` }} />
                    </div>
                    <span className="font-mono text-xs">MAPE {report.forecast.mape}%</span>
                  </div>
                )}
              </div>
              <p className="mt-4 rounded-xl border border-amber-400/30 bg-amber-400/10 p-3 text-sm text-amber-400">
                ⚠️ {report.forecast.reliability_statement}
              </p>
            </div>
          </section>
        )}

        {/* predict — on-demand ML forecast */}
        <section id="predict" className="mt-12 scroll-mt-32">
          <h2 className="font-heading mb-1 text-xl font-bold">🔮 {tr.predict.title}</h2>
          <p className="mb-4 text-sm text-dim">{tr.predict.subtitle}</p>
          <PredictPanel sessionId={id} />
        </section>

        {/* recommendations */}
        {report.recommendations.length > 0 && (
          <section id="recommendations" className="mt-12 scroll-mt-32">
            <h2 className="font-heading mb-4 text-xl font-bold">✅ {tr.recommendations}</h2>
            <ol className="space-y-3">
              {report.recommendations.map((r, i) => (
                <motion.li key={i} initial={{ opacity: 0, x: -10 }} whileInView={{ opacity: 1, x: 0 }}
                  viewport={{ once: true }} transition={{ delay: i * 0.07 }}
                  className="card flex items-start gap-3.5 p-4 text-sm">
                  <span className="grid h-7 w-7 shrink-0 place-items-center rounded-lg bg-grad-iris font-mono text-xs font-bold text-white">
                    {i + 1}
                  </span>
                  <span className="self-center text-fg">{r}</span>
                </motion.li>
              ))}
            </ol>
          </section>
        )}

        {/* data quality */}
        <section id="quality" className="mt-12 scroll-mt-32">
          <h2 className="font-heading mb-4 text-xl font-bold">🩺 {tr.quality}</h2>
          <div className="card p-6">
            {quality ? (
              <div className="grid gap-8 md:grid-cols-[200px_1fr]">
                <div className="text-center">
                  <motion.div initial={{ scale: 0.7, opacity: 0 }} whileInView={{ scale: 1, opacity: 1 }}
                    viewport={{ once: true }}
                    className={`mx-auto grid h-28 w-28 place-items-center rounded-full border-8 ${
                      quality.score >= 85 ? "border-mint-500" : quality.score >= 60 ? "border-amber-400" : "border-rose-400"}`}>
                    <span className="font-mono text-2xl font-bold">{quality.score}</span>
                  </motion.div>
                  <div className="mt-2 flex items-center justify-center gap-1 font-mono text-xs text-dim">
                    <BadgeCheck size={13} /> /100
                  </div>
                </div>
                <div className="space-y-4">
                  <Bar label={tr.completeness} value={quality.dimensions.completeness} />
                  <Bar label={tr.uniqueness} value={quality.dimensions.uniqueness} />
                  <Bar label={tr.consistency} value={quality.dimensions.consistency} />
                  <Bar label={tr.validity} value={quality.dimensions.validity} />
                </div>
              </div>
            ) : <div className="skeleton h-32 w-full" />}

            {report.data_quality_notes && (
              <p className="mt-5 text-sm text-muted">{report.data_quality_notes}</p>
            )}
            {report.cleaning_log.length > 0 && (
              <div className="mt-5">
                <h3 className="kicker mb-3">{tr.cleaningLog}</h3>
                <ol className="relative space-y-3 border-s-2 border-indigo-500/30 ps-5">
                  {report.cleaning_log.map((e, i) => (
                    <li key={i} className="relative text-sm">
                      <span className="absolute -start-[27px] top-1 h-3 w-3 rounded-full bg-indigo-500" />
                      <span className="font-medium">{e.action}</span>
                      {e.column && <span className="text-dim"> · {e.column}</span>}
                      {e.before_count != null && e.after_count != null && (
                        <span className="ms-2 font-mono text-xs text-dim">
                          {e.before_count.toLocaleString()} → {e.after_count.toLocaleString()}
                        </span>
                      )}
                      <div className="text-xs text-dim">{e.justification}</div>
                    </li>
                  ))}
                </ol>
              </div>
            )}
          </div>
        </section>
      </div>

      {/* floating ask button (mobile) */}
      <button onClick={() => setChatOpen(true)} aria-label="ask"
        className="btn-grad fixed bottom-6 end-6 z-30 grid h-14 w-14 place-items-center rounded-full shadow-lift sm:hidden">
        <MessageCircleQuestion size={22} />
      </button>

      {/* chart drill-down modal */}
      <AnimatePresence>
        {zoomChart && (
          <motion.div className="fixed inset-0 z-50 grid place-items-center bg-black/50 p-4 backdrop-blur-sm"
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            onClick={() => setZoomChart(null)}>
            <motion.div initial={{ scale: 0.94 }} animate={{ scale: 1 }} exit={{ scale: 0.94 }}
              className="card-raised w-full max-w-4xl p-4" onClick={(e) => e.stopPropagation()}>
              <div className="mb-2 flex justify-end">
                <button onClick={() => setZoomChart(null)} aria-label="close"
                  className="rounded-lg p-1.5 text-dim transition hover:text-fg"><X size={18} /></button>
              </div>
              <RemoteChart sessionId={id} name={zoomChart} height={520} />
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      <ChatDrawer sessionId={id} open={chatOpen} onClose={() => setChatOpen(false)} />
    </main>
  );
}
