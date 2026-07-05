export const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/** Read the persisted auth token (zustand persists under "daa-ui") without
 *  importing the store, so this stays usable in any context. */
function authHeaders(): Record<string, string> {
  if (typeof window === "undefined") return {};
  try {
    const raw = window.localStorage.getItem("daa-ui");
    const token = raw ? JSON.parse(raw)?.state?.token : null;
    return token ? { Authorization: `Bearer ${token}` } : {};
  } catch {
    return {};
  }
}

/** fetch wrapper that injects the auth header on every request. */
function _fetch(url: string, init: RequestInit = {}): Promise<Response> {
  return fetch(url, { ...init, headers: { ...authHeaders(), ...(init.headers || {}) } });
}

async function json<T>(resp: Response): Promise<T> {
  if (!resp.ok) {
    let detail = resp.statusText;
    try { detail = (await resp.json()).detail ?? detail; } catch { /* keep statusText */ }
    throw new Error(detail);
  }
  return resp.json();
}

export interface ColumnProfile {
  name: string; dtype: string; semantic_type: string;
  missing_count: number; missing_pct: number; n_unique: number;
  sample_values: unknown[];
}
export interface Profile {
  filename: string; n_rows: number; n_cols: number; duplicate_rows: number;
  columns: ColumnProfile[]; candidate_time_columns: string[]; warnings: string[];
}
export interface KPI { label: string; value: string; change?: string | null; change_direction?: string | null; }
export interface ChartMeta { name: string; title: string; json_path?: string | null; png_path?: string | null; }
export interface Finding { title: string; narrative: string; chart_name?: string | null; code?: string | null; }
export interface Anomaly { title: string; narrative: string; tag: string; chart_name?: string | null; }
export interface Segment { name: string; description: string; recommendation: string; }
export interface CleaningEntry {
  action: string; column?: string | null;
  before_count?: number | null; after_count?: number | null; justification: string;
}
export interface Forecast {
  narrative: string; model_name?: string | null; mape?: number | null;
  chart_name?: string | null; reliability_statement: string;
}
export interface Report {
  session_id: string; language: string; title: string; executive_summary: string;
  kpis: KPI[]; findings: Finding[]; cleaning_log: CleaningEntry[];
  data_quality_notes?: string | null; forecast?: Forecast | null;
  anomalies: Anomaly[]; segments: Segment[]; recommendations: string[];
  charts: ChartMeta[]; verification: Record<string, unknown>;
}
export interface Quality {
  score: number;
  dimensions: { completeness: number; uniqueness: number; consistency: number; validity: number };
  warnings: string[];
}
export interface SessionInfo { session_id: string; filename: string; status: string; created_at: string; }

export interface AuthResult { token: string; user: { id: string; email: string } }
export interface PredictValues { columns: string[]; rows: Record<string, unknown>[]; n_rows_total?: number }
export interface PredictResult {
  answer: string;
  metrics: Record<string, unknown>;
  values: PredictValues | null;
  chart: ChartMeta | null;
  method?: string;
  verification: Record<string, unknown>;
}

export const api = {
  register: (email: string, password: string) =>
    _fetch(`${API}/auth/register`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    }).then((r) => json<AuthResult>(r)),
  login: (email: string, password: string) =>
    _fetch(`${API}/auth/login`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    }).then((r) => json<AuthResult>(r)),
  logout: () => _fetch(`${API}/auth/logout`, { method: "POST" }).then((r) => r.ok),
  upload: (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return _fetch(`${API}/upload`, { method: "POST", body: fd })
      .then((r) => json<{ session_id: string; profile: Profile }>(r));
  },
  uploadSample: (id: string) =>
    _fetch(`${API}/samples/${id}`, { method: "POST" })
      .then((r) => json<{ session_id: string; profile: Profile }>(r)),
  samples: () => _fetch(`${API}/samples`).then((r) => json<{ id: string; filename: string }[]>(r)),
  sessions: () => _fetch(`${API}/sessions`).then((r) => json<SessionInfo[]>(r)),
  analyze: (session_id: string, goal: string | null, language: string) =>
    _fetch(`${API}/analyze`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id, goal, language }),
    }).then((r) => json<{ status: string }>(r)),
  status: (id: string) =>
    _fetch(`${API}/analyze/${id}/status`).then((r) =>
      json<{ status: string; progress: number; message: string; error?: string }>(r)),
  report: (id: string) => _fetch(`${API}/report/${id}/json`).then((r) => json<Report>(r)),
  chartJson: (id: string, name: string) =>
    _fetch(`${API}/sessions/${id}/charts/${encodeURIComponent(name)}/json`)
      .then((r) => json<{ data: object[]; layout: object }>(r)),
  quality: (id: string) => _fetch(`${API}/sessions/${id}/quality`).then((r) => json<Quality>(r)),
  suggestions: (id: string) =>
    _fetch(`${API}/sessions/${id}/suggestions`).then((r) => json<{ suggestions: string[] }>(r)),
  chat: (id: string, question: string, language: string) =>
    _fetch(`${API}/chat`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: id, question, language }),
    }).then((r) => json<{ answer: string }>(r)),
  scenario: (id: string, description: string) =>
    _fetch(`${API}/sessions/${id}/scenario`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ description }),
    }).then((r) => json<{
      answer: string; expected_outcome?: number; best_case?: number; worst_case?: number;
      baseline?: number; charts: ChartMeta[];
    }>(r)),
  columns: (id: string) =>
    _fetch(`${API}/sessions/${id}/columns`).then((r) =>
      json<{ columns: { name: string; semantic_type: string; numeric: boolean }[]; numeric: string[] }>(r)),
  predict: (id: string, body: { target?: string; horizon?: number; frequency?: string; model?: string }) =>
    _fetch(`${API}/sessions/${id}/predict`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then((r) => json<PredictResult>(r)),
  progressUrl: (id: string) => `${API}/sessions/${id}/progress`,
  exportUrls: (id: string) => ({
    pdf: `${API}/report/${id}/pdf`,
    html: `${API}/report/${id}`,
    pptx: `${API}/sessions/${id}/presentation/pptx`,
    slides: `${API}/sessions/${id}/presentation/slides`,
    cleanedCsv: `${API}/data/${id}/cleaned.csv`,
  }),
};
