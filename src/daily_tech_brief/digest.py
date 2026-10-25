"""Digest generation for Telegram HTML, Plain-Text, and Responsive Email HTML."""

from __future__ import annotations

import html
import logging
from datetime import datetime
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

from daily_tech_brief.models import Article

logger = logging.getLogger(__name__)

CATEGORY_DISPLAY_NAMES = {
    "ai_and_llms": "AI & LLMs",
    "software_dev": "Software Development",
    "cybersecurity": "Cybersecurity Watch",
    "internships_and_hackathons": "Internships & Opportunities",
    "startups_and_industry": "Big Tech & Startups",
    "research_and_opensource": "Research & Open Source",
}


def format_timestamp(dt: Optional[datetime], tz: ZoneInfo) -> str:
    """Format publication timestamp nicely or report unknown."""
    if not dt:
        return "Unknown date"
    local_dt = dt.astimezone(tz)
    return local_dt.strftime("%d %b %Y, %I:%M %p %Z")


def group_articles_by_category(articles: List[Article]) -> Dict[str, List[Article]]:
    """Group articles into logical digest sections."""
    sections: Dict[str, List[Article]] = {}
    for a in articles:
        primary = a.categories[0] if a.categories else "software_dev"
        sections.setdefault(primary, []).append(a)
    return sections


class DigestRenderer:
    """Renders formatted digests for Plain-Text, Telegram HTML, and Email HTML."""

    def __init__(self, tz: ZoneInfo) -> None:
        self.tz = tz

    def render_plain_text(
        self,
        articles: List[Article],
        digest_date_str: str,
        generated_at: datetime,
        is_fallback_window: bool = False,
    ) -> str:
        """Render clean, human-readable plain text digest."""
        lines: List[str] = []
        gen_time_str = generated_at.astimezone(self.tz).strftime("%I:%M %p %Z")
        window_str = "Coverage window: past 48 hours (fallback window for low-news volume)" if is_fallback_window else "Coverage window: past 24 hours"

        lines.append("=" * 60)
        lines.append("DAILY TECH BRIEF")
        lines.append(f"{digest_date_str} | Generated at: {gen_time_str}")
        lines.append(window_str)
        lines.append("=" * 60)
        lines.append("")

        if not articles:
            lines.append("No major qualifying news items found today within the lookback window.")
            lines.append("")
            return "\n".join(lines)

        sections = group_articles_by_category(articles)

        for cat_id, cat_articles in sections.items():
            cat_title = CATEGORY_DISPLAY_NAMES.get(cat_id, cat_id.replace("_", " ").title())
            lines.append(f"--- {cat_title.upper()} ---")
            lines.append("")

            for idx, a in enumerate(cat_articles, start=1):
                lines.append(f"• {a.title}")
                lines.append(f"  Source: {a.source_name} | Published: {format_timestamp(a.published_at, self.tz)}")

                if a.is_opportunity and a.opportunity_data:
                    opp = a.opportunity_data
                    lines.append(f"  Type: {opp.opportunity_type} | Location: {opp.location}")
                    if opp.deadline:
                        lines.append(f"  Deadline: {opp.deadline} (Status: {opp.verification_status})")
                    if opp.eligibility:
                        lines.append(f"  Eligibility: {opp.eligibility}")

                if a.summary:
                    lines.append(f"  Summary: {a.summary}")
                if a.why_it_matters:
                    lines.append(f"  Why it matters: {a.why_it_matters}")
                if a.technical_context:
                    lines.append(f"  Technical context: {a.technical_context}")

                lines.append(f"  Link: {a.original_url}")
                if a.corroborating_sources:
                    corrob = ", ".join(s["source_name"] for s in a.corroborating_sources[:2])
                    lines.append(f"  Also covered by: {corrob}")
                lines.append("")

        # Source Notes
        lines.append("-" * 60)
        lines.append("SOURCE NOTES:")
        lines.append("• Publication timestamps may be missing or inaccurate in source feeds.")
        lines.append("• Preprints and research papers have not necessarily been peer-reviewed.")
        lines.append("• Opportunity deadlines & eligibility are marked verified only when checked.")
        lines.append("• Summaries are reading aids; refer to the original links for full context.")
        lines.append("=" * 60)

        return "\n".join(lines)

    def render_telegram_html(
        self,
        articles: List[Article],
        digest_date_str: str,
        generated_at: datetime,
        is_fallback_window: bool = False,
    ) -> List[str]:
        """Render Telegram-compliant HTML messages, splitting if length exceeds limit (4000 chars)."""
        gen_time_str = generated_at.astimezone(self.tz).strftime("%I:%M %p %Z")
        window_str = "<i>Coverage: past 48h (fallback)</i>" if is_fallback_window else "<i>Coverage: past 24h</i>"

        header = (
            f"⚡ <b>DAILY TECH BRIEF</b>\n"
            f"📅 <b>{html.escape(digest_date_str)}</b> | {gen_time_str}\n"
            f"{window_str}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
        )

        if not articles:
            return [header + "No qualifying stories found today within the active lookback window."]

        chunks: List[str] = []
        current_chunk = header

        sections = group_articles_by_category(articles)

        for cat_id, cat_articles in sections.items():
            cat_title = CATEGORY_DISPLAY_NAMES.get(cat_id, cat_id.replace("_", " ").title())
            section_header = f"📌 <b>{html.escape(cat_title.upper())}</b>\n\n"

            if len(current_chunk) + len(section_header) > 3600:
                chunks.append(current_chunk.strip())
                current_chunk = section_header
            else:
                current_chunk += section_header

            for a in cat_articles:
                safe_title = html.escape(a.title)
                safe_source = html.escape(a.source_name)
                safe_url = html.escape(a.original_url)
                pub_time = format_timestamp(a.published_at, self.tz)

                story_lines = [
                    f"▪️ <a href=\"{safe_url}\"><b>{safe_title}</b></a>",
                    f"   🏛 <i>{safe_source}</i> | 🕒 {pub_time}",
                ]

                if a.is_opportunity and a.opportunity_data:
                    opp = a.opportunity_data
                    opp_info = f"   🎯 <b>{html.escape(opp.opportunity_type)}</b> ({html.escape(opp.location)})"
                    if opp.deadline:
                        opp_info += f" | ⏳ <i>Due: {html.escape(opp.deadline)}</i>"
                    story_lines.append(opp_info)

                if a.summary:
                    story_lines.append(f"   💡 {html.escape(a.summary)}")
                if a.why_it_matters:
                    story_lines.append(f"   🎯 <b>Why it matters:</b> {html.escape(a.why_it_matters)}")

                story_lines.append("")
                story_text = "\n".join(story_lines) + "\n"

                if len(current_chunk) + len(story_text) > 3800:
                    chunks.append(current_chunk.strip())
                    current_chunk = story_text
                else:
                    current_chunk += story_text

        footer = (
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"ℹ️ <i>Summaries are automated reading aids. Check original links for authoritative details.</i>"
        )
        if len(current_chunk) + len(footer) > 4000:
            chunks.append(current_chunk.strip())
            chunks.append(footer)
        else:
            current_chunk += footer
            chunks.append(current_chunk.strip())

        return chunks

    def render_email_html(
        self,
        articles: List[Article],
        digest_date_str: str,
        generated_at: datetime,
        is_fallback_window: bool = False,
    ) -> str:
        """Render responsive, beautifully styled HTML email with mobile card layout."""
        gen_time_str = generated_at.astimezone(self.tz).strftime("%I:%M %p %Z")
        window_label = "Past 48 Hours (Fallback Window)" if is_fallback_window else "Past 24 Hours"

        sections = group_articles_by_category(articles)
        sections_html = []

        for cat_id, cat_articles in sections.items():
            cat_name = CATEGORY_DISPLAY_NAMES.get(cat_id, cat_id.replace("_", " ").title())
            cards_html = []

            for a in cat_articles:
                safe_title = html.escape(a.title)
                safe_source = html.escape(a.source_name)
                safe_url = html.escape(a.original_url)
                pub_time = format_timestamp(a.published_at, self.tz)

                opp_badge = ""
                if a.is_opportunity and a.opportunity_data:
                    opp = a.opportunity_data
                    dl_str = f" | Due: {html.escape(opp.deadline)}" if opp.deadline else ""
                    opp_badge = (
                        f'<div style="margin: 6px 0; padding: 6px 10px; background-color: #f0fdf4; border: 1px solid #bbf7d0; '
                        f'border-radius: 6px; font-size: 13px; color: #166534;">'
                        f'<strong>🎯 {html.escape(opp.opportunity_type)}</strong> ({html.escape(opp.location)}){dl_str}'
                        f'</div>'
                    )

                summary_html = f'<p style="margin: 8px 0 4px 0; color: #374151; font-size: 14px; line-height: 1.5;">{html.escape(a.summary)}</p>' if a.summary else ""
                why_matters_html = (
                    f'<p style="margin: 4px 0 8px 0; color: #1f2937; font-size: 13px; line-height: 1.4;">'
                    f'<strong>Why it matters:</strong> {html.escape(a.why_it_matters)}'
                    f'</p>'
                ) if a.why_it_matters else ""

                card = f"""
                <div style="background-color: #ffffff; border: 1px solid #e5e7eb; border-radius: 8px; padding: 16px; margin-bottom: 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.05);">
                    <div style="font-size: 12px; color: #6b7280; margin-bottom: 6px;">
                        <span style="font-weight: 600; color: #4b5563;">{safe_source}</span> &bull; <span>{pub_time}</span>
                    </div>
                    <h3 style="margin: 0 0 8px 0; font-size: 17px; font-weight: 600; line-height: 1.35;">
                        <a href="{safe_url}" style="color: #2563eb; text-decoration: none;" target="_blank">{safe_title}</a>
                    </h3>
                    {opp_badge}
                    {summary_html}
                    {why_matters_html}
                    <div style="margin-top: 10px;">
                        <a href="{safe_url}" style="display: inline-block; font-size: 13px; font-weight: 500; color: #2563eb; text-decoration: none;" target="_blank">
                            Read Original Source &rarr;
                        </a>
                    </div>
                </div>
                """
                cards_html.append(card)

            section_block = f"""
            <div style="margin-top: 24px;">
                <h2 style="font-size: 16px; font-weight: 700; color: #111827; text-transform: uppercase; letter-spacing: 0.05em; border-bottom: 2px solid #e5e7eb; padding-bottom: 6px; margin-bottom: 14px;">
                    {html.escape(cat_name)}
                </h2>
                {''.join(cards_html)}
            </div>
            """
            sections_html.append(section_block)

        content_body = "".join(sections_html) if articles else "<p style='color: #6b7280;'>No major qualifying news items were found within the lookback window.</p>"

        return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Daily Tech Brief - {html.escape(digest_date_str)}</title>
</head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f9fafb; margin: 0; padding: 20px; color: #111827;">
    <div style="max-width: 640px; margin: 0 auto; background-color: #ffffff; border-radius: 12px; overflow: hidden; border: 1px solid #e5e7eb; padding: 24px;">
        <!-- Header -->
        <div style="border-bottom: 2px solid #2563eb; padding-bottom: 16px; margin-bottom: 20px;">
            <div style="font-size: 12px; font-weight: 700; color: #2563eb; letter-spacing: 0.1em; text-transform: uppercase;">Daily Personal Tech Brief</div>
            <h1 style="margin: 4px 0 8px 0; font-size: 24px; font-weight: 800; color: #111827;">{html.escape(digest_date_str)}</h1>
            <div style="font-size: 13px; color: #6b7280;">
                Generated at <strong>{gen_time_str}</strong> &bull; Coverage: <strong>{window_label}</strong>
            </div>
        </div>

        <!-- Digest Sections -->
        {content_body}

        <!-- Footer / Source Notes -->
        <div style="margin-top: 32px; padding-top: 16px; border-top: 1px solid #e5e7eb; font-size: 12px; color: #6b7280; line-height: 1.5;">
            <p style="margin: 0 0 6px 0;"><strong>Source Notes:</strong></p>
            <ul style="margin: 0; padding-left: 18px;">
                <li>Timestamps depend on publisher feed accuracy.</li>
                <li>Preprints and research papers are pre-peer-review.</li>
                <li>Opportunity deadlines are verified when checked against official pages.</li>
                <li>Summaries are reading aids; visit the source for full context.</li>
            </ul>
        </div>
    </div>
</body>
</html>"""
