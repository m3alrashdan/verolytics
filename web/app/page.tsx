"use client";
import { motion } from "framer-motion";
import {
  ArrowRight, BadgeCheck, Braces, Check, FileText, GitCompareArrows,
  TrendingUp, UploadCloud,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import Onboarding from "@/components/Onboarding";
import TopBar from "@/components/TopBar";
import { useToast } from "@/components/Providers";
import { api, type SessionInfo } from "@/lib/api";
import { t } from "@/lib/i18n";
import { useUI } from "@/lib/store";

type SampleMeta = { en: string; ar: string; meta: string; tint: string; spark: string };
const SAMPLE_LABELS: Record<string, SampleMeta> = {
  "ecommerce-sales": { en: "E-commerce Sales", ar: "مبيعات متجر إلكتروني", meta: "12 cols · 18k rows", tint: "var(--violet)", spark: "0,22 16,18 32,21 48,10 64,14 80,5 96,8" },
  "arabic-sales": { en: "Arabic Sales Data", ar: "بيانات مبيعات عربية", meta: "9 cols · 6.2k rows", tint: "var(--cyan)", spark: "0,18 16,20 32,12 48,15 64,7 80,11 96,4" },
  "financial-report": { en: "Financial Report", ar: "تقرير مالي", meta: "14 cols · 3.1k rows", tint: "var(--magenta)", spark: "0,24 16,16 32,19 48,12 64,16 80,9 96,6" },
  "hr-data": { en: "HR Data", ar: "بيانات موارد بشرية", meta: "11 cols · 940 rows", tint: "var(--verified)", spark: "0,20 16,14 32,17 48,9 64,13 80,7 96,10" },
};
const FALLBACK_TINTS = ["var(--violet)", "var(--cyan)", "var(--magenta)", "var(--verified)"];
const VP_ICONS = [Braces, GitCompareArrows, TrendingUp];

export default function UploadPage() {
  const router = useRouter();
  const toast = useToast();
  const lang = useUI((s) => s.lang);
  const tr = t(lang);
  const [dragOver, setDragOver] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [samples, setSamples] = useState<{ id: string }[]>([]);
  const [recent, setRecent] = useState<SessionInfo[]>([]);
  const fileInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    api.samples().then(setSamples).catch(() => {});
    api.sessions().then((s) => setRecent(s.slice(0, 4))).catch(() => {});
  }, []);

  const ingest = useCallback(async (file: File) => {
    setBusy(file.name);
    try {
      const { session_id } = await api.upload(file);
      router.push(`/analyze/${session_id}`);
    } catch (e) {
      toast(String((e as Error).message ?? e), "err");
      setBusy(null);
    }
  }, [router, toast]);

  const ingestSample = useCallback(async (id: string) => {
    setBusy(id);
    try {
      const { session_id } = await api.uploadSample(id);
      router.push(`/analyze/${session_id}`);
    } catch (e) {
      toast(String((e as Error).message ?? e), "err");
      setBusy(null);
    }
  }, [router, toast]);

  const seeSample = () => {
    const done = recent.find((r) => r.status === "done");
    if (done) router.push(`/report/${done.session_id}`);
    else if (samples[0]) void ingestSample(samples[0].id);
    else fileInput.current?.click();
  };

  return (
    <main className="min-h-screen">
      <Onboarding />
      <TopBar />
      <div className="mx-auto max-w-[1280px] px-4 pb-20 pt-10 sm:px-6 lg:px-10 lg:pt-16">

        {/* hero + dropzone */}
        <section className="grid items-center gap-10 lg:grid-cols-2 lg:gap-16">
          <motion.div initial={{ opacity: 0, y: 18 }} animate={{ opacity: 1, y: 0 }}>
            <span className="inline-flex items-center gap-2 rounded-full border border-line bg-[var(--bg-2)] px-3.5 py-1.5 font-mono text-[12px] tracking-wide text-muted">
              <span className="h-[7px] w-[7px] rounded-full" style={{ background: "var(--verified)", boxShadow: "0 0 10px var(--verified)" }} />
              {tr.heroEyebrow}
            </span>
            <h1 className="mt-5 font-heading text-[clamp(38px,6.4vw,64px)] font-semibold leading-[1.02] tracking-[-0.03em]">
              <span className="block">{tr.heroTitle1}</span>
              <span className="grad-text block">{tr.heroTitle2}</span>
            </h1>
            <p className="mt-5 max-w-[30em] text-[clamp(16px,1.7vw,18px)] leading-relaxed text-muted">{tr.tagline}</p>
            <div className="mt-7 flex flex-wrap gap-3">
              <button onClick={() => fileInput.current?.click()} disabled={!!busy}
                className="btn-grad inline-flex h-[50px] items-center gap-2.5 rounded-[13px] px-6 text-[15px] font-semibold">
                <UploadCloud size={18} /> {tr.ctaUpload}
              </button>
              <button onClick={seeSample} disabled={!!busy}
                className="inline-flex h-[50px] items-center gap-2.5 rounded-[13px] border border-line-strong bg-[var(--bg-2)] px-5 text-[15px] font-semibold text-fg transition hover:border-[var(--violet)] hover:bg-[var(--bg-3)]">
                {tr.ctaSample} <ArrowRight size={17} className="rtl:rotate-180" />
              </button>
            </div>
            <div className="mt-5 inline-flex items-center gap-2.5 text-[13.5px] text-dim">
              <Check size={15} style={{ color: "var(--verified)" }} /> {tr.trustMicro}
            </div>
          </motion.div>

          {/* dropzone */}
          <motion.div initial={{ opacity: 0, y: 18 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.12 }}
            onClick={() => fileInput.current?.click()}
            onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
            onDragLeave={() => setDragOver(false)}
            onDrop={(e) => { e.preventDefault(); setDragOver(false); const f = e.dataTransfer.files?.[0]; if (f) void ingest(f); }}
            className={`relative grid cursor-pointer place-items-center rounded-[22px] border p-12 text-center transition-colors ${
              dragOver ? "border-[var(--violet)] bg-[var(--nx-accent-soft)]" : "border-line bg-[var(--bg-1)]"}`}
            style={{ boxShadow: "var(--shadow)" }}>
            {/* aurora gradient ring */}
            <span aria-hidden className="pointer-events-none absolute inset-0 rounded-[inherit] p-px opacity-60"
              style={{ background: "var(--grad-aurora)", WebkitMask: "linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0)", WebkitMaskComposite: "xor", maskComposite: "exclude" }} />
            <input ref={fileInput} type="file" accept=".csv,.xlsx,.xls" hidden
              onChange={(e) => { const f = e.target.files?.[0]; if (f) void ingest(f); }} />
            <span className="grid h-[60px] w-[60px] place-items-center rounded-[18px] border border-line bg-[var(--bg-3)]"
              style={{ color: "var(--violet-ink)", animation: "floaty 6s ease-in-out infinite" }}>
              <UploadCloud size={26} />
            </span>
            {busy ? (
              <>
                <div className="mt-4 font-mono text-sm font-medium">{busy}</div>
                <div className="skeleton mt-3 h-2 w-48" />
              </>
            ) : (
              <>
                <div className="mt-4 font-heading text-[19px] font-semibold">{dragOver ? tr.dropActive : tr.dropTitle}</div>
                <div className="mt-1 text-sm text-muted">{tr.dropSub}</div>
                <div className="mt-4 flex flex-wrap justify-center gap-1.5">
                  {["CSV", "XLSX", tr.dropLimit].map((c) => (
                    <span key={c} className="rounded-md bg-[var(--bg-3)] px-2.5 py-1 font-mono text-[11.5px] text-muted">{c}</span>
                  ))}
                </div>
              </>
            )}
          </motion.div>
        </section>

        {/* samples */}
        {samples.length > 0 && (
          <section className="mt-16 lg:mt-24">
            <h2 className="font-heading text-[clamp(22px,3vw,28px)] font-semibold tracking-[-0.02em]">{tr.samplesH}</h2>
            <p className="mt-1.5 text-[15px] text-muted">{tr.samplesSub}</p>
            <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              {samples.map(({ id }, i) => {
                const m = SAMPLE_LABELS[id];
                const tint = m?.tint ?? FALLBACK_TINTS[i % FALLBACK_TINTS.length];
                const spark = m?.spark ?? "0,20 24,12 48,16 72,8 96,6";
                return (
                  <motion.button key={id}
                    initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.05 * i }}
                    whileHover={{ y: -3 }} disabled={!!busy} onClick={() => void ingestSample(id)}
                    className="card group p-5 text-start transition hover:border-line-strong">
                    <div className="flex items-center justify-between">
                      <span className="grid h-10 w-10 place-items-center rounded-[11px] border border-line bg-[var(--bg-3)]" style={{ color: tint }}>
                        <FileText size={19} />
                      </span>
                      <svg width="64" height="24" viewBox="0 0 96 30" fill="none" preserveAspectRatio="none" className="overflow-visible">
                        <polyline points={spark} fill="none" stroke={tint} strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
                      </svg>
                    </div>
                    <div className="mt-4 text-base font-semibold">{m ? (lang === "ar" ? m.ar : m.en) : id}</div>
                    <div className="mt-1 font-mono text-[12.5px] text-dim">{m?.meta ?? id}</div>
                    <div className="mt-3.5 inline-flex items-center gap-1.5 text-[13px] font-semibold" style={{ color: tint }}>
                      {tr.analyze} <ArrowRight size={15} className="transition group-hover:translate-x-0.5 rtl:rotate-180" />
                    </div>
                  </motion.button>
                );
              })}
            </div>
          </section>
        )}

        {/* recent + value props */}
        <section className="mt-14 grid gap-10 lg:mt-20 lg:grid-cols-2 lg:gap-14">
          {recent.length > 0 && (
            <div>
              <h2 className="mb-4 font-heading text-[clamp(20px,2.6vw,25px)] font-semibold tracking-[-0.02em]">{tr.recent}</h2>
              <div className="flex flex-col gap-2.5">
                {recent.map((s) => {
                  const st = s.status === "done"
                    ? { bg: "var(--verified-bg)", fg: "var(--verified-ink)", label: tr.verified }
                    : s.status === "failed"
                      ? { bg: "var(--danger-bg)", fg: "var(--danger)", label: tr.failed }
                      : { bg: "var(--nx-accent-soft)", fg: "var(--violet-ink)", label: tr.analyzing };
                  return (
                    <button key={s.session_id}
                      onClick={() => router.push(s.status === "done" ? `/report/${s.session_id}` : `/analyze/${s.session_id}`)}
                      className="flex items-center gap-3.5 rounded-[14px] border border-line bg-[var(--bg-1)] p-3.5 text-start transition hover:border-line-strong">
                      <span className="grid h-[38px] w-[38px] shrink-0 place-items-center rounded-[10px] bg-[var(--bg-3)] text-muted">
                        <FileText size={18} />
                      </span>
                      <div className="min-w-0 flex-1">
                        <div className="truncate font-mono text-sm font-medium">{s.filename}</div>
                        <div className="mt-0.5 text-[12.5px] text-dim">
                          {new Date(s.created_at + "Z").toLocaleString(lang === "ar" ? "ar" : "en", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}
                        </div>
                      </div>
                      <span className="inline-flex shrink-0 items-center gap-1.5 rounded-full px-2.5 py-1 text-[11.5px] font-semibold"
                        style={{ background: st.bg, color: st.fg }}>
                        <span className="h-[5px] w-[5px] rounded-full" style={{ background: st.fg }} /> {st.label}
                      </span>
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          <div>
            <h2 className="mb-4 font-heading text-[clamp(20px,2.6vw,25px)] font-semibold tracking-[-0.02em]">{tr.vp.h}</h2>
            <div className="flex flex-col gap-3">
              {tr.vp.items.map((v, i) => {
                const Icon = VP_ICONS[i] ?? BadgeCheck;
                const iconBg = ["var(--vp-icon-bg)", "var(--cyan-icon-bg)", "var(--magenta-icon-bg)"][i] ?? "var(--vp-icon-bg)";
                const iconFg = ["var(--violet-ink)", "var(--cyan-ink)", "var(--magenta)"][i] ?? "var(--violet-ink)";
                return (
                  <div key={i} className="flex gap-3.5 rounded-[14px] border border-line bg-[var(--bg-1)] p-4">
                    <span className="grid h-[38px] w-[38px] shrink-0 place-items-center rounded-[10px]" style={{ background: iconBg, color: iconFg }}>
                      <Icon size={18} />
                    </span>
                    <div>
                      <div className="text-[15.5px] font-semibold">{v.t}</div>
                      <div className="mt-1 text-[13.5px] leading-relaxed text-muted">{v.d}</div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </section>
      </div>
    </main>
  );
}
