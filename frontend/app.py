"""Streamlit frontend for the Data Analyst Agent.

Design language matches the generated report: teal accent on warm cream,
card-based layout, EN/AR with full RTL.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import requests
import streamlit as st
import streamlit.components.v1 as components

API_URL = os.environ.get("API_URL", "http://localhost:8000")
SAMPLES_DIR = Path(__file__).resolve().parents[1] / "evaluation" / "datasets"

# --------------------------------------------------------------- i18n ----

TEXTS = {
    "en": {
        "tagline": "Upload a raw data file — get a cleaned dataset, interactive charts, "
                   "KPIs and a professional report. Every number is verified against executed code.",
        "upload": "Drop a CSV or XLSX file here (up to 25 MB)",
        "or_sample": "…or try a sample dataset",
        "goal": "What do you want to learn from this data? (optional)",
        "goal_ph": "e.g. Which products drive revenue, and where are we losing money?",
        "analyze": "🚀 Analyze",
        "analyzing": "The agent is working…",
        "rows": "Rows", "cols": "Columns", "dupes": "Duplicate rows", "missing": "Missing cells",
        "health": "Data health", "preview_cols": "Columns", "missing_chart": "Missing values by column",
        "types_chart": "Column types",
        "tab_report": "📊 Report", "tab_charts": "📈 Charts", "tab_clean": "🧹 Cleaning log",
        "tab_chat": "💬 Ask the data", "tab_download": "⬇️ Downloads",
        "verified": "numbers verified", "redacted_warn": "Some unverifiable numbers were redacted.",
        "exec_summary": "Executive summary", "findings": "Key findings", "recs": "Recommendations",
        "forecast": "Forecast", "reliability": "Reliability",
        "chat_ph": "e.g. Which month had the highest revenue?",
        "chat_hint": "Questions run real code against your data — answers are verified too.",
        "dl_pdf": "Report (PDF)", "dl_html": "Report (HTML)", "dl_csv": "Cleaned data (CSV)",
        "failed": "Analysis failed", "retry": "Try again",
        "history": "Recent sessions", "new": "➕ New analysis",
        "step": "Step", "status": "Status", "no_findings": "No findings available.",
        "full_report": "Open the full formatted report",
        "plan": "Analysis plan", "rationale": "Why",
        "quality": "Data quality notes",
        "col": "column", "action": "action", "before": "before", "after": "after",
        "justification": "justification",
    },
    "ar": {
        "tagline": "ارفع ملف بيانات خام — واحصل على بيانات نظيفة ورسوم تفاعلية ومؤشرات وتقرير احترافي. "
                   "كل رقم يتم التحقق منه مقابل كود منفَّذ فعلياً.",
        "upload": "أسقط ملف CSV أو XLSX هنا (حتى 25 ميغابايت)",
        "or_sample": "…أو جرّب بيانات تجريبية",
        "goal": "ماذا تريد أن تعرف من هذه البيانات؟ (اختياري)",
        "goal_ph": "مثال: أي المنتجات تقود الإيرادات، وأين نخسر المال؟",
        "analyze": "🚀 حلّل",
        "analyzing": "الوكيل يعمل الآن…",
        "rows": "الصفوف", "cols": "الأعمدة", "dupes": "صفوف مكررة", "missing": "خلايا مفقودة",
        "health": "صحة البيانات", "preview_cols": "الأعمدة", "missing_chart": "القيم المفقودة حسب العمود",
        "types_chart": "أنواع الأعمدة",
        "tab_report": "📊 التقرير", "tab_charts": "📈 الرسوم", "tab_clean": "🧹 سجل التنظيف",
        "tab_chat": "💬 اسأل بياناتك", "tab_download": "⬇️ التنزيلات",
        "verified": "رقماً تم التحقق منه", "redacted_warn": "تم حجب أرقام تعذّر التحقق منها.",
        "exec_summary": "الملخص التنفيذي", "findings": "أبرز النتائج", "recs": "التوصيات",
        "forecast": "التنبؤ", "reliability": "الموثوقية",
        "chat_ph": "مثال: أي شهر حقق أعلى إيرادات؟",
        "chat_hint": "الأسئلة تشغّل كوداً حقيقياً على بياناتك — والإجابات موثّقة أيضاً.",
        "dl_pdf": "التقرير (PDF)", "dl_html": "التقرير (HTML)", "dl_csv": "البيانات النظيفة (CSV)",
        "failed": "فشل التحليل", "retry": "أعد المحاولة",
        "history": "الجلسات الأخيرة", "new": "➕ تحليل جديد",
        "step": "الخطوة", "status": "الحالة", "no_findings": "لا توجد نتائج.",
        "full_report": "افتح التقرير الكامل المنسّق",
        "plan": "خطة التحليل", "rationale": "السبب",
        "quality": "ملاحظات جودة البيانات",
        "col": "العمود", "action": "الإجراء", "before": "قبل", "after": "بعد",
        "justification": "المبرر",
    },
}

# ------------------------------------------------------------- styling ----

CSS = """
<style>
:root {
  --accent:#0e6e6e; --accent-soft:#e2efee; --ink:#1c2733; --muted:#5b6b7a;
  --up:#157f3d; --down:#b3261e; --card:#ffffff; --line:#dfe7e5;
}
.block-container { padding-top: 1.6rem; max-width: 1150px; }

.hero {
  background: linear-gradient(120deg, #0e6e6e 0%, #14897f 55%, #2aa18f 100%);
  border-radius: 18px; padding: 26px 32px; color: #fff; margin-bottom: 18px;
  box-shadow: 0 8px 24px rgba(14,110,110,.25);
}
.hero h1 { margin: 0 0 6px; font-size: 1.7rem; color:#fff; }
.hero p  { margin: 0; opacity: .92; font-size: .98rem; max-width: 60rem; }

.metric-row { display:flex; gap:14px; flex-wrap:wrap; margin: 6px 0 4px; }
.metric-card {
  flex:1; min-width:150px; background:var(--card); border:1px solid var(--line);
  border-radius:14px; padding:14px 18px; box-shadow:0 2px 8px rgba(28,39,51,.05);
}
.metric-card .v { font-size:1.5rem; font-weight:700; color:var(--accent); }
.metric-card .l { font-size:.82rem; color:var(--muted); margin-top:2px; }
.metric-card .c { font-size:.85rem; font-weight:600; margin-top:4px; }
.metric-card .c.up { color:var(--up); } .metric-card .c.down { color:var(--down); }
.metric-card .c.flat { color:var(--muted); }

.finding-card {
  background:var(--card); border:1px solid var(--line); border-radius:14px;
  padding:18px 22px; margin-bottom:14px; box-shadow:0 2px 8px rgba(28,39,51,.05);
}
.finding-card h4 { margin:0 0 8px; color:var(--accent); }

.badge {
  display:inline-block; background:var(--accent-soft); color:var(--accent);
  border-radius:999px; padding:3px 12px; font-size:.8rem; font-weight:600;
}
.badge.warn { background:#fdf3e0; color:#8a5a00; }

.rec-list li { margin-bottom:8px; }
div[data-testid="stFileUploader"] section {
  border:2px dashed var(--accent); border-radius:14px; background:var(--accent-soft);
}
.stTabs [data-baseweb="tab-list"] { gap: 6px; }
.stTabs [data-baseweb="tab"] {
  background:#fff; border:1px solid var(--line); border-radius:10px 10px 0 0; padding:8px 16px;
}
.stTabs [aria-selected="true"] { background:var(--accent-soft); border-bottom-color:var(--accent); }
</style>
"""

RTL_CSS = """
<style>
.block-container, .hero, .finding-card, .metric-card { direction: rtl; text-align: right; }
.stTabs [data-baseweb="tab-list"] { direction: rtl; }
</style>
"""

# --------------------------------------------------------------- helpers ----

def api(method: str, path: str, **kwargs):
    try:
        resp = getattr(requests, method)(f"{API_URL}{path}", timeout=kwargs.pop("timeout", 60), **kwargs)
        return resp
    except requests.ConnectionError:
        st.error(f"Cannot reach the API at {API_URL} — is the backend running?")
        st.stop()


def kpi_cards(kpis: list[dict]) -> str:
    cards = []
    for k in kpis:
        change = ""
        if k.get("change"):
            direction = k.get("change_direction") or "flat"
            arrow = {"up": "▲", "down": "▼", "flat": "•"}.get(direction, "•")
            change = f'<div class="c {direction}">{arrow} {k["change"]}</div>'
        cards.append(f'<div class="metric-card"><div class="v">{k.get("value","")}</div>'
                     f'<div class="l">{k.get("label","")}</div>{change}</div>')
    return f'<div class="metric-row">{"".join(cards)}</div>'


def stat_cards(items: list[tuple[str, str]]) -> str:
    cards = "".join(f'<div class="metric-card"><div class="v">{v}</div><div class="l">{l}</div></div>'
                    for l, v in items)
    return f'<div class="metric-row">{cards}</div>'


def reset_session() -> None:
    for key in ("session_id", "profile", "report", "report_html", "chat_history", "uploaded_name"):
        st.session_state.pop(key, None)


# ----------------------------------------------------------------- page ----

st.set_page_config(page_title="Data Analyst Agent", page_icon="📊", layout="wide")
st.markdown(CSS, unsafe_allow_html=True)

with st.sidebar:
    st.markdown("### 📊 Data Analyst Agent")
    language = st.radio("Language / اللغة", ["en", "ar"],
                        format_func=lambda v: "English" if v == "en" else "العربية",
                        label_visibility="collapsed")
    t = TEXTS[language]
    st.divider()
    if st.button(t["new"], use_container_width=True):
        reset_session()
        st.rerun()
    # session history
    hist = api("get", "/sessions", timeout=10)
    if hist.status_code == 200 and hist.json():
        st.caption(t["history"])
        for s in hist.json()[:8]:
            icon = {"done": "✅", "failed": "⚠️"}.get(s["status"], "⏳")
            if st.button(f'{icon} {s["filename"][:24]}', key=f'h{s["session_id"]}',
                         use_container_width=True):
                reset_session()
                st.session_state.session_id = s["session_id"]
                st.session_state.uploaded_name = s["filename"]
                if s["status"] == "done":
                    st.session_state.report_loaded_from_history = True
                st.rerun()

if language == "ar":
    st.markdown(RTL_CSS, unsafe_allow_html=True)

st.markdown(f"""<div class="hero"><h1>📊 Data Analyst Agent</h1><p>{t["tagline"]}</p></div>""",
            unsafe_allow_html=True)

st.session_state.setdefault("session_id", None)
st.session_state.setdefault("chat_history", [])


def do_upload(name: str, payload: bytes) -> None:
    resp = api("post", "/upload", files={"file": (name, payload)}, timeout=180)
    if resp.status_code != 200:
        st.error(resp.json().get("detail", resp.text))
        return
    data = resp.json()
    reset_session()
    st.session_state.session_id = data["session_id"]
    st.session_state.profile = data["profile"]
    st.session_state.uploaded_name = name


# ------------------------------------------------------------- 1. upload ----

if st.session_state.session_id is None:
    uploaded = st.file_uploader(t["upload"], type=["csv", "xlsx", "xls"])
    if uploaded is not None:
        with st.spinner("…"):
            do_upload(uploaded.name, uploaded.getvalue())
        if st.session_state.session_id:
            st.rerun()
    if SAMPLES_DIR.exists():
        st.caption(t["or_sample"])
        samples = ["01_clean_sales.csv", "03_arabic_columns.csv", "09_financial.csv", "10_hr.csv"]
        cols = st.columns(len(samples))
        for c, name in zip(cols, samples):
            p = SAMPLES_DIR / name
            if p.exists() and c.button(name.split("_", 1)[1].replace(".csv", ""),
                                       key=f"s{name}", use_container_width=True):
                with st.spinner("…"):
                    do_upload(name, p.read_bytes())
                st.rerun()
    st.stop()

# ------------------------------------------------- 2. profile + analyze ----

session_id = st.session_state.session_id
status = api("get", f"/analyze/{session_id}/status", timeout=30).json()
profile = st.session_state.get("profile")

if status["status"] in ("uploaded", "failed") and not st.session_state.get("report_loaded_from_history"):
    if profile:
        n_rows, n_cols = profile["n_rows"], profile["n_cols"]
        missing_cells = sum(c["missing_count"] for c in profile["columns"])
        st.markdown(stat_cards([
            (t["rows"], f"{n_rows:,}"), (t["cols"], str(n_cols)),
            (t["dupes"], f'{profile["duplicate_rows"]:,}'), (t["missing"], f"{missing_cells:,}"),
        ]), unsafe_allow_html=True)
        with st.expander(f'🩺 {t["health"]} — {st.session_state.get("uploaded_name","")}', expanded=False):
            import plotly.express as px

            left, right = st.columns([3, 2])
            with left:
                st.caption(t["preview_cols"])
                st.dataframe(
                    [{"column": c["name"], "type": c["semantic_type"],
                      "missing %": c["missing_pct"], "unique": c["n_unique"],
                      "sample": ", ".join(str(v) for v in c["sample_values"][:3])}
                     for c in profile["columns"]],
                    use_container_width=True, height=260)
            with right:
                miss = [(c["name"], c["missing_pct"]) for c in profile["columns"] if c["missing_pct"] > 0]
                if miss:
                    fig = px.bar(x=[m[1] for m in miss], y=[m[0] for m in miss], orientation="h",
                                 labels={"x": "%", "y": ""}, title=t["missing_chart"],
                                 color_discrete_sequence=["#0e6e6e"])
                    fig.update_layout(height=240, margin=dict(l=0, r=0, t=40, b=0),
                                      paper_bgcolor="rgba(0,0,0,0)")
                    st.plotly_chart(fig, use_container_width=True)
                types: dict[str, int] = {}
                for c in profile["columns"]:
                    types[c["semantic_type"]] = types.get(c["semantic_type"], 0) + 1
                fig2 = px.pie(values=list(types.values()), names=list(types.keys()),
                              title=t["types_chart"],
                              color_discrete_sequence=px.colors.sequential.Teal)
                fig2.update_layout(height=240, margin=dict(l=0, r=0, t=40, b=0),
                                   paper_bgcolor="rgba(0,0,0,0)")
                st.plotly_chart(fig2, use_container_width=True)
            for w in profile.get("warnings", []):
                st.warning(w)

    if status["status"] == "failed":
        st.error(f'{t["failed"]}: {status.get("error")}')

    goal = st.text_input(t["goal"], placeholder=t["goal_ph"])
    if st.button(t["analyze"] if status["status"] != "failed" else f'{t["analyze"]} ({t["retry"]})',
                 type="primary", use_container_width=True):
        resp = api("post", "/analyze", json={"session_id": session_id,
                                             "goal": goal or None, "language": language}, timeout=30)
        if resp.status_code != 200:
            st.error(resp.json().get("detail", resp.text))
        else:
            st.rerun()
    st.stop()

# ----------------------------------------------------- 3. live progress ----

if status["status"] not in ("done", "failed"):
    bar = st.progress(min(max(status.get("progress", 0.0), 0.0), 1.0),
                      text=status.get("message") or t["analyzing"])
    plan_box = st.empty()
    while True:
        time.sleep(2)
        status = api("get", f"/analyze/{session_id}/status", timeout=30).json()
        bar.progress(min(max(status.get("progress", 0.0), 0.0), 1.0),
                     text=status.get("message") or t["analyzing"])
        plan = status.get("plan")
        steps_done = {s["step_number"]: s for s in status.get("steps", [])}
        if plan:
            lines = []
            for ps in plan["analysis_steps"]:
                n = ps["step_number"]
                icon = "✅" if steps_done.get(n, {}).get("status") == "done" else (
                    "⏭️" if steps_done.get(n, {}).get("status") == "skipped" else "⏳")
                lines.append({t["step"]: f'{icon} {n}', "": ps["description"]})
            with plan_box.container():
                st.caption(f'🗺️ {t["plan"]}')
                st.table(lines)
        if status["status"] in ("done", "failed"):
            st.rerun()

if status["status"] == "failed":
    st.error(f'{t["failed"]}: {status.get("error")}')
    if st.button(t["retry"], type="primary"):
        api("post", "/analyze", json={"session_id": session_id, "language": language}, timeout=30)
        st.rerun()
    st.stop()

# -------------------------------------------------------- 4. the report ----

report = st.session_state.get("report")
if report is None:
    r = api("get", f"/report/{session_id}/json", timeout=60)
    if r.status_code != 200:
        st.error(r.json().get("detail", r.text))
        st.stop()
    report = r.json()
    st.session_state.report = report

ver = report.get("verification", {})
badge = (f'<span class="badge">✓ {ver.get("matched", 0)}/{ver.get("checked", 0)} {t["verified"]}</span>'
         if not ver.get("redacted")
         else f'<span class="badge warn">⚠ {t["redacted_warn"]}</span>')
st.markdown(f'## {report["title"]} &nbsp; {badge}', unsafe_allow_html=True)

tabs = st.tabs([t["tab_report"], t["tab_charts"], t["tab_clean"], t["tab_chat"], t["tab_download"]])

with tabs[0]:  # report
    if report.get("kpis"):
        st.markdown(kpi_cards(report["kpis"]), unsafe_allow_html=True)
    st.markdown(f'#### {t["exec_summary"]}')
    st.write(report["executive_summary"])
    if report.get("findings"):
        st.markdown(f'#### {t["findings"]}')
        for i, f in enumerate(report["findings"], 1):
            st.markdown(f'<div class="finding-card"><h4>{i}. {f["title"]}</h4></div>',
                        unsafe_allow_html=True)
            if f.get("chart_name"):
                components.iframe(f'{API_URL}/report/{session_id}/chart/{f["chart_name"]}',
                                  height=420)
            st.write(f["narrative"])
    if report.get("forecast"):
        fc = report["forecast"]
        st.markdown(f'#### {t["forecast"]}')
        if fc.get("chart_name"):
            components.iframe(f'{API_URL}/report/{session_id}/chart/{fc["chart_name"]}', height=420)
        st.write(fc["narrative"])
        meta = " · ".join(x for x in [fc.get("model_name"),
                                      f'MAPE {fc["mape"]}%' if fc.get("mape") is not None else None] if x)
        if meta:
            st.caption(meta)
        st.info(f'**{t["reliability"]}:** {fc["reliability_statement"]}')
    if report.get("recommendations"):
        st.markdown(f'#### {t["recs"]}')
        st.markdown('<ol class="rec-list">' +
                    "".join(f"<li>{r}</li>" for r in report["recommendations"]) + "</ol>",
                    unsafe_allow_html=True)

with tabs[1]:  # all charts
    charts = report.get("charts", [])
    if not charts:
        st.caption(t["no_findings"])
    for c in charts:
        st.markdown(f'**{c["title"]}**')
        components.iframe(f'{API_URL}/report/{session_id}/chart/{c["name"]}', height=440)

with tabs[2]:  # cleaning log
    if report.get("data_quality_notes"):
        st.markdown(f'**{t["quality"]}:** {report["data_quality_notes"]}')
    log = report.get("cleaning_log", [])
    if log:
        st.dataframe([{t["action"]: e["action"], t["col"]: e.get("column") or "—",
                       t["before"]: e.get("before_count"), t["after"]: e.get("after_count"),
                       t["justification"]: e["justification"]} for e in log],
                     use_container_width=True)

with tabs[3]:  # chat
    st.caption(t["chat_hint"])
    for q, a in st.session_state.chat_history:
        with st.chat_message("user"):
            st.write(q)
        with st.chat_message("assistant"):
            st.write(a)
    question = st.chat_input(t["chat_ph"])
    if question:
        with st.chat_message("user"):
            st.write(question)
        with st.chat_message("assistant"), st.spinner("…"):
            resp = api("post", "/chat", json={"session_id": session_id, "question": question,
                                              "language": language}, timeout=600)
            answer = (resp.json().get("answer") if resp.status_code == 200
                      else resp.json().get("detail", resp.text))
            st.write(answer)
        st.session_state.chat_history.append((question, answer))

with tabs[4]:  # downloads
    c1, c2, c3 = st.columns(3)
    with c1:
        pdf = api("get", f"/report/{session_id}/pdf", timeout=300)
        if pdf.status_code == 200:
            st.download_button(t["dl_pdf"], data=pdf.content,
                               file_name=f"report-{session_id[:8]}.pdf",
                               mime="application/pdf", use_container_width=True)
    with c2:
        html = st.session_state.get("report_html")
        if html is None:
            h = api("get", f"/report/{session_id}", timeout=60)
            html = h.text if h.status_code == 200 else None
            st.session_state.report_html = html
        if html:
            st.download_button(t["dl_html"], data=html.encode(),
                               file_name=f"report-{session_id[:8]}.html",
                               mime="text/html", use_container_width=True)
    with c3:
        csv = api("get", f"/data/{session_id}/cleaned.csv", timeout=120)
        if csv.status_code == 200:
            st.download_button(t["dl_csv"], data=csv.content,
                               file_name=f"cleaned-{session_id[:8]}.csv",
                               mime="text/csv", use_container_width=True)
    if st.session_state.get("report_html"):
        with st.expander(t["full_report"]):
            components.html(st.session_state.report_html, height=1800, scrolling=True)
