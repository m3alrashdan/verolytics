"use client";
import { motion } from "framer-motion";
import { ArrowDownRight, ArrowUpRight, Minus } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { KPI } from "@/lib/api";

/** Count-up that preserves the verified display string exactly.
 *  We animate the numeric part, then snap to the original string so the
 *  final rendered value is byte-identical to the verified KPI value. */
function useCountUp(display: string, ms = 900): string {
  const [text, setText] = useState(display);
  const raf = useRef<number>();
  useEffect(() => {
    const m = display.replace(/,/g, "").match(/-?\d+(\.\d+)?/);
    if (!m) { setText(display); return; }
    const target = parseFloat(m[0]);
    const decimals = (m[1] ?? "").length ? m[1]!.length - 1 : 0;
    const start = performance.now();
    const tick = (now: number) => {
      const p = Math.min((now - start) / ms, 1);
      const eased = 1 - Math.pow(1 - p, 3);
      if (p >= 1) { setText(display); return; }
      const current = (target * eased).toFixed(decimals);
      const formatted = Number(current).toLocaleString("en-US", {
        minimumFractionDigits: decimals, maximumFractionDigits: decimals,
      });
      setText(display.replace(/-?[\d,]+(\.\d+)?/, formatted));
      raf.current = requestAnimationFrame(tick);
    };
    raf.current = requestAnimationFrame(tick);
    return () => { if (raf.current) cancelAnimationFrame(raf.current); };
  }, [display, ms]);
  return text;
}

export default function KpiCard({ kpi, index }: { kpi: KPI; index: number }) {
  const value = useCountUp(kpi.value);
  const dir = kpi.change_direction ?? "flat";
  const Icon = dir === "up" ? ArrowUpRight : dir === "down" ? ArrowDownRight : Minus;
  const color = dir === "up" ? "text-mint-500" : dir === "down" ? "text-rose-400" : "text-dim";

  return (
    <motion.div
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.08 }}
      whileHover={{ y: -3 }}
      className="card min-w-[180px] flex-1 p-5 transition hover:border-indigo-500/50"
    >
      <div className="text-xs text-dim">{kpi.label}</div>
      <div className="mt-2 font-mono text-[27px] font-semibold tracking-[-0.5px] text-fg">
        {value}
      </div>
      {kpi.change && (
        <div className={`mt-2 flex items-center gap-1 font-mono text-sm font-semibold ${color}`}>
          <Icon size={15} /> {kpi.change}
        </div>
      )}
    </motion.div>
  );
}
