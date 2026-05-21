"""
Slack Human-in-the-Loop Notifications
---------------------------------------
Sends lead review requests to a Slack channel via Incoming Webhooks.
A reviewer reads the lead summary and email draft, then clicks Approve or Reject,
which calls back to the API to update the lead status.

Setup:
  1. Go to https://api.slack.com/apps
  2. Create a new app, enable Incoming Webhooks
  3. Add a webhook to your workspace, copy the URL
  4. Set SLACK_WEBHOOK_URL in .env

No-op mode: if SLACK_WEBHOOK_URL is not set, the notification is logged locally
and the function returns True. This means the system works out of the box
without Slack configured.
"""
import os
import json
import requests
from loguru import logger


SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")
BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")


def send_lead_review_request(lead: dict) -> bool:
    """
    Post a lead approval request to Slack.

    Returns True on success or no-op mode, False on send failure.
    Never raises. Always logs the outcome.

    Args:
        lead: Lead dict with fields: id, company_name, qualification_score,
              pain_points, outreach_email, status
    """
    company_name = lead.get("company_name", "Unknown")
    lead_id = lead.get("id", "unknown")
    score = lead.get("qualification_score", "N/A")
    industry = lead.get("industry", "N/A")
    location = lead.get("location", "N/A")
    pain_points = lead.get("pain_points") or []
    outreach_draft = lead.get("outreach_draft") or {}

    # Build email preview from the draft dict or a plain string
    if isinstance(outreach_draft, dict):
        email_body = outreach_draft.get("email_body", "")
        subject = outreach_draft.get("subject", "")
        email_preview_text = f"Subject: {subject}\n\n{email_body}"
    else:
        email_preview_text = str(outreach_draft)

    email_preview = (email_preview_text[:250] + "...") if len(email_preview_text) > 250 else email_preview_text

    # First 3 pain points as a bullet list
    top_pain_points = pain_points[:3]
    pain_points_text = "\n".join(f"- {p}" for p in top_pain_points) if top_pain_points else "- None identified"

    approve_url = f"{BASE_URL}/leads/{lead_id}/approve"
    reject_url = f"{BASE_URL}/leads/{lead_id}/reject"

    if not SLACK_WEBHOOK_URL:
        logger.info(
            f"[Slack no-op] Lead review request for '{company_name}' | "
            f"id={lead_id} score={score} industry={industry} location={location} | "
            f"pain_points={top_pain_points} | "
            f"email_preview={email_preview!r} | "
            f"approve={approve_url} reject={reject_url}"
        )
        return True

    # Use pre-built summary if available, else fall back to inline construction
    summary = lead.get("summary", "")
    summary_block_text = f"```{summary}```" if summary else (
        f"*{company_name}*  |  {industry}  |  {location}\n"
        f"Score: `{score}/10`"
    )

    key_signals = lead.get("key_signals", [])
    signals_text = "  ·  ".join(key_signals[:3]) if key_signals else "—"

    warnings_list = []
    
    # 1. Low qualification score warning
    is_low_score = False
    try:
        from core.config import get_settings
        settings = get_settings()
        if score != "N/A" and float(score) < settings.qualification_threshold:
            is_low_score = True
    except Exception:
        pass
        
    if is_low_score:
        warnings_list.append(f"⚠️ *Low Qualification Score*: `{score}/10` (Below threshold of `{settings.qualification_threshold}`)")

    # 2. Competitor auto-disqualification warning
    if lead.get("recommended_action") == "disqualify (competitor)":
        warnings_list.append("🚫 *Competitor Alert*: Lead identified as an HR/HRMS competitor")

    # 3. Hallucination guard warnings
    hallucination_action = outreach_draft.get("hallucination_action", "pass")
    hallucination_warnings = outreach_draft.get("hallucination_warnings") or []
    if hallucination_action in ("warn", "reject") or hallucination_warnings:
        emoji = "❌" if hallucination_action == "reject" else "⚠️"
        warnings_list.append(f"{emoji} *Hallucination Guard*: `{hallucination_action.upper()}`")
        for hw in hallucination_warnings:
            warnings_list.append(f"  · {hw}")

    blocks = [
        # ── Header ───────────────────────────────────────────────────────────
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"New Lead for Review",
                "emoji": False,
            },
        },
        # ── Lead summary card ────────────────────────────────────────────────
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": summary_block_text,
            },
        },
        {"type": "divider"},
    ]

    # ── Warnings block if any ────────────────────────────────────────────
    if warnings_list:
        warnings_text = "\n".join(warnings_list)
        blocks.extend([
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"🚨 *Review Alerts / System Flags:*\n{warnings_text}"
                }
            },
            {"type": "divider"}
        ])

    # ── Key signals + pain points side-by-side ───────────────────────────
    blocks.extend([
        {
            "type": "section",
            "fields": [
                {
                    "type": "mrkdwn",
                    "text": f"*Key Signals*\n{signals_text}",
                },
                {
                    "type": "mrkdwn",
                    "text": f"*Pain Points*\n{pain_points_text}",
                },
            ],
        },
        {"type": "divider"},
        # ── Email draft preview ──────────────────────────────────────────────
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Outreach Email Preview*\n```{email_preview}```",
            },
        },
        {"type": "divider"},
        # ── Approve / Reject actions ─────────────────────────────────────────
        # Bug fix: previously showed POST URLs as code snippets, which required
        # the reviewer to copy/paste them into a terminal. Now uses Slack's
        # actions block with button elements that open the GET URL directly.
        # GET /leads/{id}/approve and GET /leads/{id}/reject are supported
        # endpoints (added specifically for this Slack button pattern).
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "✅ Approve", "emoji": True},
                    "style": "primary",
                    "url": approve_url,
                    "action_id": f"approve_{lead_id}",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "❌ Reject", "emoji": True},
                    "style": "danger",
                    "url": reject_url,
                    "action_id": f"reject_{lead_id}",
                },
            ],
        },
    ])

    payload = {"blocks": blocks}

    try:
        response = requests.post(
            SLACK_WEBHOOK_URL,
            data=json.dumps(payload),
            headers={"Content-Type": "application/json"},
            timeout=5,
        )
        response.raise_for_status()
        logger.info(f"Slack review request sent for lead: {company_name}")
        return True
    except Exception as e:
        logger.warning(f"Slack notification failed for {lead.get('company_name')}: {e}")
        return False
