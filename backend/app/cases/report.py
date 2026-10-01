"""PDF export for a complete review case."""
from html import escape
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable


def _safe(value) -> str:
    return escape(str(value if value is not None else ""))


def make_pdf(case: dict) -> bytes:
    buffer = BytesIO()
    document = SimpleDocTemplate(buffer, pagesize=(595, 842), rightMargin=46,
                                 leftMargin=46, topMargin=44, bottomMargin=44)
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="CaseTitle", parent=styles["Title"], fontSize=21,
                              leading=26, textColor=colors.HexColor("#20372e"), alignment=TA_CENTER))
    styles.add(ParagraphStyle(name="CaseBody", parent=styles["BodyText"], fontSize=9,
                              leading=13, spaceAfter=5))
    styles.add(ParagraphStyle(name="CaseSmall", parent=styles["BodyText"], fontSize=8,
                              leading=11, textColor=colors.HexColor("#596a5d"), spaceAfter=4))
    styles.add(ParagraphStyle(name="CaseSection", parent=styles["Heading2"], fontSize=13,
                              leading=17, textColor=colors.HexColor("#246c50"), spaceBefore=18,
                              spaceAfter=8))
    story = [Paragraph("Sentinel-Lite Review Report", styles["CaseTitle"]),
             Spacer(1, 12), Paragraph(f"<b>Case:</b> {_safe(case['name'])}", styles["CaseBody"]),
             Paragraph(f"<b>Created:</b> {_safe(case['created_at'])}", styles["CaseBody"]),
             Paragraph("<b>Files:</b> " + ", ".join(
                 f"{_safe(kind.replace('_', ' ').title())}: {_safe(info['filename'])}"
                 for kind, info in case["files"].items()), styles["CaseBody"]),
             Paragraph("Findings require human confirmation. Retrieved passages are context for AI answers.",
                       styles["CaseSmall"]),
             HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#dce5da")),
             Paragraph("Anomaly review", styles["CaseSection"])]
    if not case["scans"]:
        story.append(Paragraph("No scans have been run for this case.", styles["CaseBody"]))
    for number, scan in enumerate(case["scans"], 1):
        story.append(Paragraph(
            f"<b>Scan {number}</b> · {_safe(scan['created_at'])} · "
            f"{scan['transactions_analyzed']} transactions · {scan['duration_ms']} ms",
            styles["CaseBody"]))
        if not scan["findings"]:
            story.append(Paragraph("No findings in this scan.", styles["CaseSmall"]))
        for order, finding in enumerate(scan["findings"], 1):
            lines = [
                Paragraph(f"<b>{number}.{order} {_safe(finding['type'].replace('_', ' ').title())}</b> "
                          f"({_safe(finding['severity'])})", styles["CaseBody"]),
                Paragraph(_safe(finding["description"]), styles["CaseBody"]),
                Paragraph(f"<b>Rule:</b> {_safe(finding.get('rule', ''))} "
                          f"<b>Calculation:</b> {_safe(finding.get('calculation', ''))}", styles["CaseSmall"]),
            ]
            for evidence in finding.get("evidence", []):
                lines.append(Paragraph(
                    f"<b>Evidence:</b> {_safe(evidence['source'])}, {_safe(evidence['location'])} "
                    f"[{_safe(', '.join(evidence.get('columns', [])))}] — "
                    f"{_safe(evidence.get('excerpt', ''))}", styles["CaseSmall"]))
            clause = finding.get("contract_clause") or {}
            if clause.get("status") == "suggested" and clause.get("evidence"):
                context = clause["evidence"]
                lines.append(Paragraph(
                    f"<b>Suggested contract context - verify:</b> {_safe(context['source'])}, "
                    f"{_safe(context['location'])} — {_safe(context.get('excerpt', ''))}",
                    styles["CaseSmall"]))
            else:
                lines.append(Paragraph("<b>Contract context:</b> No clause suggested.", styles["CaseSmall"]))
            brief = finding.get("investigation")
            if brief:
                lines.append(Paragraph(f"<b>Investigation generated:</b> {_safe(brief['created_at'])}",
                                       styles["CaseSmall"]))
                for label, field in (("What happened", "what_happened"),
                                     ("Why it matters", "why_it_matters"),
                                     ("Next action", "next_action")):
                    lines.append(Paragraph(f"<b>{label}:</b> {_safe(brief['sections'][field])}",
                                           styles["CaseSmall"]))
                for source in brief["sources"]:
                    lines.append(Paragraph(
                        f"<b>[{_safe(source['id'])}]</b> {_safe(source['source'])}, "
                        f"{_safe(source['location'])} — {_safe(source.get('excerpt', ''))}",
                        styles["CaseSmall"]))
            lines.append(Paragraph(
                f"<b>Decision:</b> {_safe((finding.get('decision') or 'Not reviewed').replace('_', ' ').title())}"
                f" · <b>Note:</b> {_safe(finding.get('note') or '—')}"
                f" · <b>Decided:</b> {_safe(finding.get('decided_at') or '—')}", styles["CaseSmall"]))
            story.extend(lines + [Spacer(1, 7)])
    story.append(Paragraph("Document intelligence", styles["CaseSection"]))
    if not case["questions"]:
        story.append(Paragraph("No document questions have been asked for this case.", styles["CaseBody"]))
    for number, question in enumerate(case["questions"], 1):
        lines = [Paragraph(f"<b>Question {number}:</b> {_safe(question['question'])}", styles["CaseBody"]),
                 Paragraph(f"<b>Answer:</b> {_safe(question['answer'])}", styles["CaseBody"]),
                 Paragraph(f"<b>Asked:</b> {_safe(question['created_at'])}", styles["CaseSmall"])]
        for source in question["sources"]:
            lines.append(Paragraph(
                f"<b>Retrieved context:</b> {_safe(source['source'])}, "
                f"{_safe(source.get('location') or 'location unavailable')} — "
                f"{_safe(source.get('text_preview', ''))}", styles["CaseSmall"]))
        story.extend(lines + [Spacer(1, 8)])
    document.build(story)
    return buffer.getvalue()
