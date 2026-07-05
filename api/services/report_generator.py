"""Render the Report model to interactive HTML (Plotly) and PDF (WeasyPrint)."""
from __future__ import annotations

import logging
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from api.models.report import Report

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "report" / "templates"
STYLES_DIR = Path(__file__).resolve().parents[2] / "report" / "styles"

_env = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=select_autoescape(["html"]),
)


def _chart_snippets(report: Report, workspace: Path, *, for_pdf: bool) -> dict[str, str]:
    """Map chart name -> embeddable HTML (interactive div or <img> for PDF)."""
    snippets: dict[str, str] = {}
    for chart in report.charts:
        if for_pdf:
            if chart.png_path and (workspace / chart.png_path).exists():
                snippets[chart.name] = (
                    f'<img class="chart-img" src="{(workspace / chart.png_path).resolve().as_uri()}" '
                    f'alt="{chart.title}"/>'
                )
        else:
            html_file = workspace / chart.html_path
            if html_file.exists():
                snippets[chart.name] = html_file.read_text(encoding="utf-8")
    return snippets


def render_html(report: Report, workspace: Path, *, for_pdf: bool = False) -> str:
    """Render the report. ``for_pdf=True`` swaps interactive charts for PNGs."""
    template = _env.get_template("report_ar.html" if report.language == "ar" else "report_en.html")
    css = (STYLES_DIR / "report.css").read_text(encoding="utf-8")
    return template.render(
        report=report,
        css=css,
        charts=_chart_snippets(report, workspace, for_pdf=for_pdf),
        for_pdf=for_pdf,
    )


def render_pdf(report: Report, workspace: Path) -> bytes:
    """HTML -> PDF via WeasyPrint (imported lazily; needs system pango/cairo)."""
    from weasyprint import HTML  # lazy: heavy native deps

    html = render_html(report, workspace, for_pdf=True)
    return HTML(string=html, base_url=str(workspace)).write_pdf()
