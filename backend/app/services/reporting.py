from __future__ import annotations

import io
import os
import smtplib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from typing import Any
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether


def _safe(value: Any) -> str:
    return escape(str(value if value is not None else ""))


def build_pdf_report(analysis: dict[str, Any]) -> bytes:
    """Build a concise, evidence-conscious PDF from a stored analysis payload."""
    output = io.BytesIO()
    doc = SimpleDocTemplate(output, pagesize=A4, rightMargin=18*mm, leftMargin=18*mm, topMargin=17*mm, bottomMargin=17*mm)
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="Muted", parent=styles["BodyText"], textColor=colors.HexColor("#64748b"), fontSize=8, leading=11))
    styles.add(ParagraphStyle(name="Section", parent=styles["Heading2"], textColor=colors.HexColor("#26364a"), spaceBefore=12, spaceAfter=6))
    story = [Paragraph("SentimentIQ", styles["Title"]), Paragraph("Customer feedback intelligence report", styles["Heading2"]), Spacer(1, 5*mm)]
    title = str(analysis.get("dataset_name", "Customer feedback"))
    story += [Paragraph(_safe(title), styles["Heading1"]), Paragraph(f"Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} · {int(analysis.get('total_reviews', 0))} reviews", styles["Muted"]), Spacer(1, 4*mm)]
    dist = analysis.get("sentiment_distribution", {}) or {}
    rows = [["Sentiment", "Reviews", "Share"]]
    for label in ("Positive", "Neutral", "Negative"):
        item = dist.get(label, {}) or {}
        rows.append([label, str(item.get("count", 0)), f"{item.get('percentage', 0)}%"])
    table = Table(rows, colWidths=[70*mm, 35*mm, 35*mm])
    table.setStyle(TableStyle([("BACKGROUND", (0,0),(-1,0),colors.HexColor("#e9eef5")),("TEXTCOLOR",(0,0),(-1,0),colors.HexColor("#26364a")),("GRID",(0,0),(-1,-1),.35,colors.HexColor("#d8e0e9")),("PADDING",(0,0),(-1,-1),7),("FONTNAME",(0,0),(-1,0),"Helvetica-Bold")]))
    story += [Paragraph("Sentiment overview", styles["Section"]), table]
    story.append(Paragraph("Key findings", styles["Section"]))
    insights = analysis.get("insights", []) or []
    if insights:
        for item in insights[:8]:
            story.append(KeepTogether([Paragraph(_safe(item.get("title", "Finding")), styles["Heading3"]), Paragraph(_safe(item.get("evidence", "")), styles["BodyText"]), Spacer(1, 2*mm)]))
    else:
        story.append(Paragraph("No summary findings were generated for this dataset.", styles["BodyText"]))
    story.append(Paragraph("Topics and complaints", styles["Section"]))
    topics = analysis.get("topics", []) or []
    topic_rows = [["Topic", "Mentions", "Negative", "Positive"]]
    for item in topics[:12]:
        topic_rows.append([str(item.get("topic", "Other")), str(item.get("count", item.get("mentions", 0))), str(item.get("negative_count", item.get("negative", 0))), str(item.get("positive_count", item.get("positive", 0)))])
    if len(topic_rows) == 1:
        story.append(Paragraph("No topic summary is available.", styles["BodyText"]))
    else:
        tt = Table(topic_rows, colWidths=[65*mm, 25*mm, 25*mm, 25*mm], repeatRows=1)
        tt.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),colors.HexColor("#e9eef5")),("GRID",(0,0),(-1,-1),.35,colors.HexColor("#d8e0e9")),("PADDING",(0,0),(-1,-1),6)]))
        story.append(tt)
    complaints = analysis.get("complaints", []) or []
    story.append(Paragraph("Complaint signals", styles["Section"]))
    if complaints:
        for c in complaints[:8]:
            topic_label = _safe(c.get("topic", "Complaint"))
            action = _safe(c.get("recommended_action", c.get("description", "Review supporting customer comments.")))
            story.append(Paragraph(f"<b>{topic_label}</b> — {action}", styles["BodyText"]))
    else:
        story.append(Paragraph("No complaint signals were generated.", styles["BodyText"]))
    story += [Spacer(1, 5*mm), Paragraph("Methodology and limitations", styles["Section"]), Paragraph(_safe(analysis.get("methodology", "SentimentIQ baseline analysis of uploaded reviews.")), styles["Muted"]), Paragraph("Sentiment and topic signals are model-assisted indicators, not calibrated probabilities or proof of cause. Review samples may be incomplete or biased. Validate important decisions against original customer feedback.", styles["Muted"])]
    doc.build(story)
    return output.getvalue()


def next_run(cadence: str, hour_utc: int, day_of_week: int, day_of_month: int, now: datetime | None = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    now = now.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
    candidate = now.replace(hour=hour_utc)
    if candidate <= now:
        candidate += timedelta(days=1)
    if cadence == "weekly":
        while candidate.weekday() != day_of_week:
            candidate += timedelta(days=1)
    elif cadence == "monthly":
        while candidate.day != min(day_of_month, 28):
            candidate += timedelta(days=1)
    return candidate


def following_run(schedule: Any, now: datetime | None = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    if schedule.cadence == "weekly":
        return next_run("weekly", schedule.hour_utc, schedule.day_of_week, schedule.day_of_month, now + timedelta(minutes=1))
    # Monthly schedules use day 1–28 to avoid month-end ambiguity.
    year, month = now.year, now.month + 1
    if month == 13:
        year, month = year + 1, 1
    return datetime(year, month, min(schedule.day_of_month, 28), schedule.hour_utc, tzinfo=timezone.utc)


def send_report_email(recipient: str, subject: str, pdf_bytes: bytes, dataset_name: str) -> tuple[bool, str | None]:
    host = os.getenv("SMTP_HOST")
    if not host:
        return False, "SMTP is not configured; PDF was generated and saved for download."
    port = int(os.getenv("SMTP_PORT", "587"))
    username, password = os.getenv("SMTP_USERNAME"), os.getenv("SMTP_PASSWORD")
    sender = os.getenv("SMTP_FROM", username or "reports@sentimentiq.local")
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, sender, recipient
    msg.set_content(f"Your scheduled SentimentIQ report for {dataset_name} is attached as a PDF.")
    msg.add_attachment(pdf_bytes, maintype="application", subtype="pdf", filename="sentimentiq-report.pdf")
    try:
        with smtplib.SMTP(host, port, timeout=15) as server:
            server.starttls()
            if username and password:
                server.login(username, password)
            server.send_message(msg)
        return True, None
    except Exception as exc:
        return False, f"Email delivery failed: {type(exc).__name__}: {exc}"
