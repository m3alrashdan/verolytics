"use client";
import { AnimatePresence, motion } from "framer-motion";
import {
  ArrowRight, BrainCircuit, Brush, Check, CheckCircle2, FileText, LineChart,
  Loader2, Search, XCircle,
} from "lucide-react";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import TopBar from "@/components/TopBar";
import RemoteChart from "@/components/Plot";
import { useToast } from "@/components/Providers";
import { api, type ChartMeta } from "@/lib/api";
import { t } from "@/lib/i18n";
import { useUI } from "@/lib/store";

type StepStatus = "pending" | "running" | "retrying" | "done" | "skipped";
interface Step { n: number; title: string; status: StepStatus; duration?: number; hypothesis?: string }

const STEP_ICONS = [Search, Brush, LineChart, BrainCircuit];

export default function AnalyzePage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const toast = useToast();
  const lang = useUI((s) => s.lang);
  const tr = t(lang);

  const [phase, setPhase] = useState<"idle" | "running" | "done" | "failed">("idle");
  const [goal, setGoal] = useState("");
  const [steps, setSteps] = useState<Step[]>([]);
  const [code, setCode] = useState("");
  const [charts, setCharts] = useState<ChartMeta[]>([]);
  const [bigChart, setBigChart] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [headline, setHeadline] = useState("");
  const [filename, setFilename] = useState("");
  const es = useRef<EventSource | null>(null);
  const typewriter = useRef<number | null>(null);

  // run header label
  useEffect(() => {
    api.sessions().then((all) => {
      const s = all.find((x) => x.session_id === id);
      if (s) setFilename(s.filename);
    }).catch(() => {});
  }, [id]);

  // resume state on reload
  useEffect(() => {
    api.status(id).then((s) => {
      if (s.status === "done") router.replace(`/report/${id}`);
      else if (s.status === "failed") { setPhase("failed"); setError(s.error ?? s.message); }
      else if (s.status !== "uploaded") { setPhase("running"); connect(); }
    }).catch(() => toast("Session not found", "err"));
    return () => { es.current?.close(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  const setStep = (n: number, patch: Partial<Step>, title?: string) =>
    setSteps((prev) => {
      const i = prev.findIndex((s) => s.n === n);
      if (i === -1) return [...prev, { n, title: title ?? `Step ${n}`, status: "pending", ...patch }];
      const next = [...prev];
      next[i] = { ...next[i], ...patch };
      return next;
    });

  const typeCode = (full: string) => {
    if (typewriter.current) cancelAnimationFrame(typewriter.current);
    let i = 0;
    const tick = () => {
      i = Math.min(i + 14, full.length);
      setCode(full.slice(0, i));
      if (i < full.length) typewriter.current = requestAnimationFrame(tick);
    };
    typewriter.current = requestAnimationFrame(tick);
  };

  const connect = useCallback(() => {
    es.current?.close();
    const src = new EventSource(api.progressUrl(id));
    es.current = src;
    src.addEventListener("plan_ready", (e) => {
      const d = JSON.parse((e as MessageEvent).data);
      setSteps([
        { n: 0, title: tr.cleaning, status: "pending" },
        ...d.steps.map((s: { step_number: number; description: string; hypothesis?: string }) => ({
          n: s.step_number, title: s.description, hypothesis: s.hypothesis,
          status: "pending" as StepStatus })),
      ]);
    });
    src.addEventListener("step_started", (e) => {
      const d = JSON.parse((e as MessageEvent).data);
      setStep(d.step_number, { status: "running" }, d.description);
      setHeadline(d.description ?? "");
    });
    src.addEventListener("code_executing", (e) => {
      const d = JSON.parse((e as MessageEvent).data);
      if (d.attempt > 1) setSteps((p) => p.map((s) => s.status === "running" ? { ...s, status: "retrying" } : s));
      typeCode(d.code ?? "");
    });
    src.addEventListener("step_completed", (e) => {
      const d = JSON.parse((e as MessageEvent).data);
      setStep(d.step_number, { status: "done", duration: d.duration_s }, d.description);
    });
    src.addEventListener("step_failed", (e) => {
      const d = JSON.parse((e as MessageEvent).data);
      setStep(d.step_number, { status: "skipped" }, d.description);
    });
    src.addEventListener("chart_ready", (e) => {
      const d = JSON.parse((e as MessageEvent).data);
      setCharts((c) => (c.some((x) => x.name === d.name) ? c : [...c, d]));
    });
    src.addEventListener("report_generating", () => setHeadline(tr.analyzing));
    src.addEventListener("report_critiquing", () => setHeadline(tr.refining));
    src.addEventListener("analysis_complete", () => {
      setPhase("done");
      src.close();
      setTimeout(() => router.push(`/report/${id}`), 900);
    });
    src.addEventListener("analysis_failed", (e) => {
      const d = JSON.parse((e as MessageEvent).data);
      setPhase("failed"); setError(d.error ?? "unknown error"); src.close();
    });
    src.onerror = () => { /* EventSource auto-reconnects */ };
  }, [id, router, tr]);

  const start = async () => {
    setPhase("running"); setError(null); setSteps([]); setCharts([]);
    try {
      connect();
      await api.analyze(id, goal || null, lang);
    } catch (e) {
      setPhase("failed"); setError(String((e as Error).message ?? e));
    }
  };

  const total = steps.length;
  const doneCount = steps.filter((s) => s.status === "done" || s.status === "skipped").length;
  const progress = phase === "done" ? 100 : total ? Math.round((doneCount / total) * 100) : 6;

  return (
    <main className="min-h-screen">
      <TopBar sessionId={id} />
      <div className="mx-auto max-w-[1280px] px-4 pb-20 pt-6 sm:px-6 lg:px-10">
        {phase === "idle" && (
          <motion.div initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }}
            className="card mx-auto max-w-xl p-8">
            <h1 className="font-heading text-2xl font-semibold">{tr.analyze}</h1>
            <label className="mt-6 block text-sm text-dim">{tr.goal}</label>
            <input value={goal} onChange={(e) => setGoal(e.target.value)} placeholder={tr.goalPh}
              className="mt-2 w-full rounded-xl border border-line-strong bg-[var(--bg-2)] px-4 py-3 text-sm text-fg outline-none transition focus:border-[var(--violet)]" />
            <button onClick={() => void start()}
              className="btn-grad mt-5 w-full rounded-xl py-3.5 font-semibold">
              🚀 {tr.analyze}
            </button>
          </motion.div>
        )}

        {phase !== "idle" && (
          <>
            {/* run header */}
            <div className="flex flex-wrap items-center gap-4 pb-4">
              <span className="grid h-[42px] w-[42px] shrink-0 place-items-center rounded-xl border border-line bg-[var(--bg-2)]" style={{ color: "var(--cyan-ink)" }}>
                <FileText size={20} />
              </span>
              <div className="min-w-0">
                <div className="truncate font-mono text-[15px] font-medium">{filename || tr.analyzing}</div>
                <div className="mt-0.5 text-[13px] text-dim">
                  {total ? `${doneCount} / ${total} · ${headline || tr.analyzing}` : tr.analyzing}
                </div>
              </div>
              {phase === "running" && (
                <span className="ms-auto inline-flex items-center gap-2 text-[13px] text-muted">
                  <Loader2 className="animate-spin" size={15} style={{ color: "var(--violet)" }} />
                  {tr.analyzing}
                </span>
              )}
            </div>
            <div className="h-[5px] overflow-hidden rounded-full border border-line bg-[var(--bg-2)]">
              <motion.div className="h-full rounded-full" style={{ background: "var(--grad-aurora)" }}
                animate={{ width: `${progress}%` }} transition={{ duration: 0.6 }} />
            </div>

            {error && (
              <div className="mt-4 rounded-[var(--r-card)] border border-rose-400/40 bg-rose-400/10 p-4 text-sm text-rose-400">
                {error}
                <button onClick={() => void start()}
                  className="ms-3 rounded-lg bg-rose-500 px-3 py-1 text-xs font-medium text-white">
                  {tr.retry}
                </button>
              </div>
            )}

            {/* done banner */}
            <AnimatePresence>
              {phase === "done" && (
                <motion.div initial={{ opacity: 0, y: 10, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }}
                  className="mt-4 flex flex-wrap items-center gap-4 rounded-[var(--r-card)] p-5"
                  style={{ background: "var(--verified-bg)", border: "1px solid var(--verified-line)" }}>
                  <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl" style={{ background: "var(--verified)", color: "#04221a" }}>
                    <Check size={22} strokeWidth={2.6} />
                  </span>
                  <div className="min-w-[180px] flex-1">
                    <div className="font-heading text-[17px] font-semibold" style={{ color: "var(--verified-ink)" }}>{tr.reportReady}</div>
                    <div className="mt-0.5 text-[13.5px] text-muted">{tr.tagline}</div>
                  </div>
                  <button onClick={() => router.push(`/report/${id}`)}
                    className="btn-grad inline-flex h-11 items-center gap-2 rounded-xl px-5 text-sm font-semibold">
                    {tr.reportReady} <ArrowRight size={16} className="rtl:rotate-180" />
                  </button>
                </motion.div>
              )}
            </AnimatePresence>

            {/* split canvas */}
            <div className="mt-5 grid items-start gap-[18px] lg:grid-cols-[minmax(0,1fr)_minmax(0,1.06fr)]">
              {/* LEFT: reasoning timeline */}
              <div className="card overflow-hidden">
                <div className="flex items-center gap-2.5 border-b border-line px-5 py-4">
                  <span className="h-2 w-2 rounded-full" style={{ background: "var(--violet)", boxShadow: "0 0 10px var(--violet)" }} />
                  <span className="font-heading text-[14.5px] font-semibold">{lang === "ar" ? "لوحة الاستدلال" : "Reasoning canvas"}</span>
                </div>
                <ol className="px-5 pb-3 pt-5">
                  {steps.length === 0 && phase === "running" && (
                    <>{[0, 1, 2].map((i) => <div key={i} className="skeleton mb-4 h-10 w-3/4" />)}</>
                  )}
                  <AnimatePresence>
                    {steps.map((s, i) => {
                      const Icon = STEP_ICONS[i % STEP_ICONS.length];
                      const active = s.status === "running" || s.status === "retrying";
                      const last = i === steps.length - 1;
                      return (
                        <motion.li key={s.n}
                          initial={{ opacity: 0, x: -12 }} animate={{ opacity: 1, x: 0 }}
                          transition={{ delay: i * 0.05 }} className="flex gap-3.5">
                          <div className="flex shrink-0 flex-col items-center">
                            <span className={`grid h-7 w-7 place-items-center rounded-full border-2 text-[12px] font-semibold transition ${
                              s.status === "done" ? "border-transparent text-white" :
                              active ? "border-[var(--violet)] text-[var(--violet-ink)]" :
                              s.status === "skipped" ? "border-rose-400 text-rose-400" :
                              "border-line-strong text-dim"}`}
                              style={s.status === "done" ? { background: "var(--verified)", color: "#04221a" } : undefined}>
                              {s.status === "done" ? <Check size={15} strokeWidth={2.6} />
                                : s.status === "skipped" ? <XCircle size={15} />
                                : active ? <Icon size={13} /> : i + 1}
                            </span>
                            {!last && <span className="my-1 w-px flex-1" style={{ background: "var(--line)", minHeight: 18 }} />}
                          </div>
                          <div className={`pb-5 ${active ? "" : ""}`}>
                            <div className="flex flex-wrap items-center gap-2.5">
                              <span className="text-sm font-medium">{s.title}</span>
                              {active && (
                                <span className="inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 font-mono text-[11px] font-semibold"
                                  style={{ background: "var(--nx-accent-soft)", color: "var(--violet-ink)" }}>
                                  <span className="h-[5px] w-[5px] animate-blink rounded-full bg-current" />
                                  {s.status === "retrying" ? "retrying" : (lang === "ar" ? "يعمل" : "running")}
                                </span>
                              )}
                            </div>
                            {s.hypothesis && (
                              <div className="mt-2 rounded-[14px] border border-line bg-[var(--bg-2)] p-3.5">
                                <div className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-wide" style={{ color: "var(--violet-ink)" }}>
                                  <BrainCircuit size={14} /> {tr.hypothesis}
                                </div>
                                <div className="mt-1.5 text-sm leading-snug">{s.hypothesis}</div>
                              </div>
                            )}
                            {s.status === "done" && s.duration != null && (
                              <div className="mt-1 inline-flex items-center gap-1.5 font-mono text-xs text-dim">
                                <CheckCircle2 size={12} style={{ color: "var(--verified)" }} /> {s.duration.toFixed(1)}s
                              </div>
                            )}
                          </div>
                        </motion.li>
                      );
                    })}
                  </AnimatePresence>
                </ol>
              </div>

              {/* RIGHT: live terminal + emerging charts */}
              <div className="flex flex-col gap-[18px] lg:sticky lg:top-[78px]">
                <div dir="ltr" className="overflow-hidden rounded-[var(--r-card)] border border-line" style={{ background: "var(--code-bg)", boxShadow: "var(--shadow)" }}>
                  <div className="flex items-center gap-2.5 border-b px-4 py-3" style={{ borderColor: "rgba(255,255,255,.07)", background: "rgba(255,255,255,.02)" }}>
                    <span className="flex gap-1.5">
                      <span className="h-[11px] w-[11px] rounded-full" style={{ background: "#ff5f57" }} />
                      <span className="h-[11px] w-[11px] rounded-full" style={{ background: "#febc2e" }} />
                      <span className="h-[11px] w-[11px] rounded-full" style={{ background: "#28c840" }} />
                    </span>
                    <span className="ms-1.5 font-mono text-[12px]" style={{ color: "#8a8a9e" }}>verolytics · python sandbox</span>
                    {phase === "running" && (
                      <span className="ms-auto inline-flex items-center gap-1.5 font-mono text-[11px]" style={{ color: "#5fd6b0" }}>
                        <span className="h-1.5 w-1.5 rounded-full" style={{ background: "#2dd4a7", boxShadow: "0 0 8px #2dd4a7" }} />
                        {lang === "ar" ? "تنفيذ مباشر" : "Live execution"}
                      </span>
                    )}
                  </div>
                  <pre className="max-h-[340px] overflow-auto px-4 py-3 font-mono text-[12.5px] leading-relaxed" style={{ color: "#c8c8d8" }}>
                    {code || <span style={{ color: "#5b5b6e" }}># waiting for the sandbox…</span>}
                    {phase === "running" && <span className="animate-blink" style={{ color: "#5fd6b0" }}>▌</span>}
                  </pre>
                </div>

                {/* emerging charts */}
                <div>
                  <h2 className="kicker mb-3">{tr.chartsAppear}</h2>
                  <div className="space-y-3">
                    {charts.length === 0 && <div className="skeleton h-28 w-full" />}
                    <AnimatePresence>
                      {charts.map((c) => (
                        <motion.button key={c.name}
                          initial={{ opacity: 0, scale: 0.92 }} animate={{ opacity: 1, scale: 1 }}
                          onClick={() => setBigChart(c.name)}
                          className="card block w-full overflow-hidden p-2 text-start transition hover:border-line-strong">
                          <div className="truncate px-1 pb-1 text-xs font-medium">{c.title}</div>
                          <div className="pointer-events-none">
                            <RemoteChart sessionId={id} name={c.name} height={120} />
                          </div>
                        </motion.button>
                      ))}
                    </AnimatePresence>
                  </div>
                </div>
              </div>
            </div>
          </>
        )}
      </div>

      {/* full-size chart modal */}
      <AnimatePresence>
        {bigChart && (
          <motion.div className="fixed inset-0 z-50 grid place-items-center bg-black/50 p-4 backdrop-blur-sm"
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            onClick={() => setBigChart(null)}>
            <motion.div initial={{ scale: 0.94 }} animate={{ scale: 1 }}
              className="card w-full max-w-3xl p-4" onClick={(e) => e.stopPropagation()}>
              <RemoteChart sessionId={id} name={bigChart} height={460} />
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </main>
  );
}
