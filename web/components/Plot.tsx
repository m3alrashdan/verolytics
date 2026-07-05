"use client";
import dynamic from "next/dynamic";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useUI } from "@/lib/store";

const Plotly = dynamic(() => import("react-plotly.js"), {
  ssr: false,
  loading: () => <div className="skeleton h-[360px] w-full" />,
});

const FONT_FAMILY = "IBM Plex Sans, IBM Plex Sans Arabic, sans-serif";
// Vibrant "Aurora" palette: violet · cyan · emerald · amber · fuchsia · blue.
const DARK_LAYOUT = {
  paper_bgcolor: "rgba(0,0,0,0)",
  plot_bgcolor: "rgba(0,0,0,0)",
  font: { color: "#b9b4cf", family: FONT_FAMILY },
  colorway: ["#a78bfa", "#22d3ee", "#34d399", "#fbbf24", "#e879f9", "#60a5fa"],
  xaxis: { gridcolor: "rgba(255,255,255,0.07)", zerolinecolor: "rgba(255,255,255,0.13)" },
  yaxis: { gridcolor: "rgba(255,255,255,0.07)", zerolinecolor: "rgba(255,255,255,0.13)" },
};
const LIGHT_LAYOUT = {
  paper_bgcolor: "rgba(0,0,0,0)",
  plot_bgcolor: "rgba(0,0,0,0)",
  font: { color: "#4b4760", family: FONT_FAMILY },
  colorway: ["#7c3aed", "#06b6d4", "#10b981", "#f59e0b", "#d946ef", "#3b82f6"],
  xaxis: { gridcolor: "rgba(28,22,58,0.07)", zerolinecolor: "rgba(28,22,58,0.13)" },
  yaxis: { gridcolor: "rgba(28,22,58,0.07)", zerolinecolor: "rgba(28,22,58,0.13)" },
};

// Continuous colorscales for heatmaps / value-shaded traces, so they blend
// into the earthy theme instead of Plotly's bright defaults. Diverging is the
// common case here (correlation heatmaps, centered on 0): dusty blue → cream
// → terracotta. Sequential (sand → ochre → clay) is used for magnitude colorbars.
const EARTHY_DIVERGING: [number, string][] = [[0, "#06b6d4"], [0.5, "#f1eefb"], [1, "#7c3aed"]];
const EARTHY_SEQUENTIAL: [number, string][] = [[0, "#ede9fe"], [0.5, "#a78bfa"], [1, "#6d28d9"]];
const CONTINUOUS_TYPES = new Set(["heatmap", "heatmapgl", "contour", "histogram2d", "histogram2dcontour"]);

type FigureJson = { data: Record<string, unknown>[]; layout: Record<string, unknown> };

export function ChartFigure({ fig, height = 380, typeOverride }: {
  fig: FigureJson; height?: number; typeOverride?: "bar" | "scatter" | "area" | null;
}) {
  const theme = useUI((s) => s.theme);
  const themed = theme === "dark" ? DARK_LAYOUT : LIGHT_LAYOUT;
  const data = fig.data.map((trace) => {
    const t: Record<string, unknown> = { ...trace };
    const ttype = String(t.type ?? "");
    // recolor continuous/heatmap traces to the earthy diverging scale
    if (CONTINUOUS_TYPES.has(ttype) || "colorscale" in t) {
      t.colorscale = EARTHY_DIVERGING;
      t.autocolorscale = false;
    }
    // recolor value-shaded marker colorbars (e.g. scatter coloured by a metric)
    const marker = t.marker as Record<string, unknown> | undefined;
    if (marker && "colorscale" in marker) {
      t.marker = { ...marker, colorscale: EARTHY_SEQUENTIAL, autocolorscale: false };
    }
    if (typeOverride === "bar") { t.type = "bar"; delete t.fill; }
    if (typeOverride === "scatter") { t.type = "scatter"; t.mode = "lines+markers"; delete t.fill; }
    if (typeOverride === "area") { t.type = "scatter"; t.mode = "lines"; t.fill = "tozeroy"; }
    return t;
  });
  const baseLayout = fig.layout as Record<string, unknown>;
  const themedAxes = themed as { xaxis?: object; yaxis?: object };
  // px.imshow-based heatmaps colour via a shared coloraxis rather than the trace
  const baseColoraxis = (baseLayout.coloraxis as object) ?? {};
  return (
    <Plotly
      data={data as never}
      layout={{
        ...baseLayout, ...themed, autosize: true, height,
        margin: { l: 50, r: 20, t: 48, b: 44 },
        xaxis: { ...(baseLayout.xaxis as object), ...themedAxes.xaxis },
        yaxis: { ...(baseLayout.yaxis as object), ...themedAxes.yaxis },
        coloraxis: { ...baseColoraxis, colorscale: EARTHY_DIVERGING, autocolorscale: false },
      } as never}
      config={{ displaylogo: false, responsive: true,
                modeBarButtonsToRemove: ["lasso2d", "select2d"] } as never}
      style={{ width: "100%" }}
      useResizeHandler
    />
  );
}

export default function RemoteChart({ sessionId, name, height = 380, typeOverride }: {
  sessionId: string; name: string; height?: number;
  typeOverride?: "bar" | "scatter" | "area" | null;
}) {
  const [fig, setFig] = useState<FigureJson | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    api.chartJson(sessionId, name)
      .then((f) => alive && setFig(f as FigureJson))
      .catch((e) => alive && setError(String(e.message ?? e)));
    return () => { alive = false; };
  }, [sessionId, name]);

  if (error) return <div className="p-4 text-sm text-dim">chart unavailable: {error}</div>;
  if (!fig) return <div className="skeleton w-full" style={{ height }} />;
  return <ChartFigure fig={fig} height={height} typeOverride={typeOverride} />;
}
