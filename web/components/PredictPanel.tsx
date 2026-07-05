"use client";
import { AnimatePresence, motion } from "framer-motion";
import { Download, Loader2, Sparkles, TrendingUp } from "lucide-react";
import { useEffect, useState } from "react";
import RemoteChart from "@/components/Plot";
import { api, type PredictResult } from "@/lib/api";
import { t } from "@/lib/i18n";
import { useUI } from "@/lib/store";

const MODELS = ["auto", "RandomForest", "GradientBoosting", "Linear"];

/** On-demand ML forecast: pick a target + model + horizon, train, and show its
 *  accuracy, drivers, the predicted values (with interval), and a chart. */
export default function PredictPanel({ sessionId }: { sessionId: string }) {
  const lang = useUI((s) => s.lang);
  const tr = t(lang).predict;
  const [target, setTarget] = useState("");
  const [model, setModel] = useState("auto");
  const [horizon, setHorizon] = useState(12);
  const [numericCols, setNumericCols] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [res, setRes] = useState<PredictResult | null>(null);

  useEffect(() => {
    api.columns(sessionId).then((c) => setNumericCols(c.numeric)).catch(() => {});
  }, [sessionId]);

  const run = async () => {
    if (busy) return;
    setBusy(true); setError(null);
    try {
      setRes(await api.predict(sessionId, {
        target: target.trim() || undefined, horizon,
        model: model === "auto" ? undefined : model,
      }));
    } catch (e) {
      setError(String((e as Error).message ?? e));
    } finally {
      setBusy(false);
    }
  };

  const m = res?.metrics ?? {};
  const num = (k: string) => (typeof m[k] === "number" ? (m[k] as number) : undefined);
  const cols = res?.values?.columns ?? [];
  const rows = res?.values?.rows ?? [];

  const downloadCsv = () => {
    if (!cols.length) return;
    const esc = (v: unknown) => {
      const s = String(v ?? "");
      return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
    };
    const csv = [cols.join(","), ...rows.map((r) => cols.map((c) => esc(r[c])).join(","))].join("\n");
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `forecast-${(m.target as string) || "values"}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="card p-6">
      <div className="flex flex-wrap items-end gap-3">
        <div className="min-w-[180px] flex-1">
          <label className="text-xs text-dim">{tr.target}</label>
          {numericCols.length > 0 ? (
            <select value={target} onChange={(e) => setTarget(e.target.value)}
              className="mt-1 w-full rounded-xl border border-line-strong bg-surface px-3 py-2.5 text-sm text-fg outline-none transition focus:border-accent">
              <option value="">{tr.targetPh}</option>
              {numericCols.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
          ) : (
            <input value={target} onChange={(e) => setTarget(e.target.value)} placeholder={tr.targetPh}
              className="mt-1 w-full rounded-xl border border-line-strong bg-surface px-3 py-2.5 text-sm text-fg outline-none transition focus:border-accent" />
          )}
        </div>
        <div className="w-40">
          <label className="text-xs text-dim">{tr.modelLabel}</label>
          <select value={model} onChange={(e) => setModel(e.target.value)}
            className="mt-1 w-full rounded-xl border border-line-strong bg-surface px-3 py-2.5 text-sm text-fg outline-none transition focus:border-accent">
            {MODELS.map((mo) => <option key={mo} value={mo}>{mo === "auto" ? tr.auto : mo}</option>)}
          </select>
        </div>
        <div className="w-24">
          <label className="text-xs text-dim">{tr.horizon}</label>
          <input type="number" min={1} max={365} value={horizon}
            onChange={(e) => setHorizon(Math.max(1, Number(e.target.value) || 1))}
            className="mt-1 w-full rounded-xl border border-line-strong bg-surface px-3 py-2.5 text-sm text-fg outline-none transition focus:border-accent" />
        </div>
        <button onClick={run} disabled={busy}
          className="btn-grad flex items-center gap-2 rounded-xl px-5 py-2.5 font-semibold disabled:opacity-50">
          {busy ? <Loader2 size={16} className="animate-spin" /> : <TrendingUp size={16} />}
          {busy ? tr.running : tr.run}
        </button>
      </div>

      {error && (
        <p className="mt-4 rounded-xl border border-rose-400/40 bg-rose-400/10 p-3 text-sm text-rose-400">
          {error}
        </p>
      )}

      <AnimatePresence>
        {res && (
          <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="mt-6 space-y-6">
            {/* accuracy */}
            <div>
              <h3 className="kicker mb-2">{tr.accuracy}</h3>
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
                <Metric label={tr.model} value={String(m.model ?? "—")} wide />
                <Metric label={tr.mape} value={num("mape") != null ? `${num("mape")}%` : "—"} hint={tr.lowerAcc} />
                <Metric label={tr.rmse} value={num("rmse")?.toLocaleString() ?? "—"} hint={tr.lowerAcc} />
                <Metric label={tr.mae} value={num("mae")?.toLocaleString() ?? "—"} hint={tr.lowerAcc} />
                <Metric label={tr.r2} value={num("r2") != null ? String(num("r2")) : "—"} hint={tr.higherAcc} />
                <Metric label={`${tr.trainRows}/${tr.testRows}`}
                  value={`${num("train_rows") ?? "—"}/${num("test_rows") ?? "—"}`} />
              </div>
            </div>

            {/* drivers (feature importances) */}
            {(() => {
              const imp = m.feature_importances as Record<string, number> | undefined;
              if (!imp || Object.keys(imp).length === 0) return null;
              const max = Math.max(...Object.values(imp), 0.0001);
              return (
                <div>
                  <h3 className="kicker mb-2">{tr.drivers}</h3>
                  <div className="space-y-1.5">
                    {Object.entries(imp).sort((a, b) => b[1] - a[1]).map(([k, v]) => (
                      <div key={k} className="flex items-center gap-3 text-xs">
                        <span className="w-24 shrink-0 truncate text-dim">{k}</span>
                        <div className="h-2 flex-1 rounded-full bg-line">
                          <div className="h-2 rounded-full bg-accent" style={{ width: `${(v / max) * 100}%` }} />
                        </div>
                        <span className="w-12 shrink-0 text-end font-mono text-dim">{(v * 100).toFixed(0)}%</span>
                      </div>
                    ))}
                  </div>
                </div>
              );
            })()}

            {/* chart */}
            {res.chart && (
              <div className="overflow-hidden rounded-xl border border-line">
                <RemoteChart sessionId={sessionId} name={res.chart.name} height={320} />
              </div>
            )}

            {/* predicted values */}
            {rows.length > 0 && (
              <div>
                <div className="mb-2 flex items-center justify-between">
                  <h3 className="kicker flex items-center gap-1.5"><Sparkles size={13} /> {tr.values}</h3>
                  <button onClick={downloadCsv}
                    className="pill flex items-center gap-1.5 px-3 py-1.5 text-xs text-dim transition hover:text-fg">
                    <Download size={13} /> {tr.downloadCsv}
                  </button>
                </div>
                <div className="overflow-x-auto rounded-xl border border-line">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-line text-start text-xs text-dim">
                        {cols.map((c) => <th key={c} className="px-3 py-2 text-start font-medium">{c}</th>)}
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map((row, i) => (
                        <tr key={i} className="border-b border-line/60 last:border-0">
                          {cols.map((c) => (
                            <td key={c} className="px-3 py-2 font-mono text-[13px]">
                              {fmt(row[c])}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {/* narrative */}
            {res.answer && <p className="text-sm leading-relaxed text-muted">{res.answer}</p>}
            {res.method === "fallback" && <p className="text-xs text-dim">{tr.fallbackNote}</p>}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function Metric({ label, value, hint, wide }: {
  label: string; value: string; hint?: string; wide?: boolean;
}) {
  return (
    <div className={`rounded-xl border border-line bg-surface p-3 ${wide ? "col-span-2 sm:col-span-1" : ""}`}>
      <div className="text-[11px] text-dim">{label}</div>
      <div className="mt-0.5 truncate font-mono text-[15px] font-semibold text-fg" title={value}>{value}</div>
      {hint && <div className="mt-0.5 text-[10px] text-dim">{hint}</div>}
    </div>
  );
}

function fmt(v: unknown): string {
  if (typeof v === "number") return v.toLocaleString(undefined, { maximumFractionDigits: 2 });
  return String(v ?? "");
}
