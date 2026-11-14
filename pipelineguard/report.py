"""Portable, escaped HTML and JSON evidence without raw input rows."""
import html
import json
from pathlib import Path


def write_report(directory, report):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    (directory / 'report.json').write_text(json.dumps(report, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    escaped = html.escape(json.dumps(report, indent=2, allow_nan=False))
    title = html.escape(report.get('title', 'PipelineGuard report'))
    status = html.escape(report.get('status', 'recorded').upper())
    findings = report.get('findings', [])
    cards = ''.join(f'<tr><td>{html.escape(str(f["code"]))}</td><td>{html.escape(str(f.get("column") or "—"))}</td><td>{html.escape(str(f.get("row") or "—"))}</td><td>{html.escape(str(f.get("detail") or ""))}</td></tr>' for f in findings)
    (directory / 'report.html').write_text(f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>{title}</title><style>body{{font:16px system-ui;background:#0d1727;color:#e7efff;max-width:1050px;margin:48px auto;padding:24px}}h1{{color:#83ead1}}.badge{{display:inline-block;padding:8px 16px;background:#243955;border-radius:20px}}table{{width:100%;border-collapse:collapse;margin:24px 0}}th,td{{text-align:left;border-bottom:1px solid #354662;padding:12px;overflow-wrap:anywhere}}pre{{background:#17263c;padding:24px;border-radius:12px;white-space:pre-wrap;overflow-wrap:anywhere}}a{{color:#83ead1}}</style><h1>PipelineGuard / {title}</h1><p class="badge">{status}</p><p>Contract-driven checks · explicit repair plan · local execution · zero model calls</p><p><a href="report.json">JSON evidence</a></p><h2>Findings</h2><table><tr><th>Check</th><th>Column</th><th>CSV row</th><th>Detail</th></tr>{cards or '<tr><td colspan="4">No findings in this report.</td></tr>'}</table><h2>Evidence</h2><pre>{escaped}</pre></html>''', encoding='utf-8')
