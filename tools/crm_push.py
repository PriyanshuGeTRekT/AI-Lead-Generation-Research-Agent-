"""
CRM Push — Webhook & Google Sheets
-------------------------------------
Pushes qualified leads to the sales team's CRM automatically after approval.

Two backends supported (configured via .env):

1. Webhook (default, recommended)
   Set CRM_WEBHOOK_URL to any endpoint:
   - HubSpot:   use a Zapier/Make webhook that creates a HubSpot contact
   - Zoho CRM:  use Zoho Flow or Make webhook
   - Notion:    use Make or n8n to create a Notion database row
   - Custom:    your own API endpoint

   Payload is a flat JSON dict with all lead fields. Works with any
   integration platform that accepts JSON webhooks.

2. Google Sheets (optional)
   Set GOOGLE_SHEETS_ID and GOOGLE_SERVICE_ACCOUNT_JSON.
   Appends one row per lead to the named sheet.
   Requires: pip install gspread google-auth

No-op mode: if neither is configured, logs the push and returns True.
This means the system works out of the box without CRM configured.
"""
import json
import requests
from typing import Dict
from loguru import logger
from core.config import get_settings

settings = get_settings()


def _flatten_lead(lead: Dict) -> Dict:
    """
    Flatten a Lead dict to a simple key-value map suitable for CRM fields.
    Lists become semicolon-separated strings. Nested dicts are JSON strings.
    """
    outreach = lead.get("outreach_draft") or {}
    sequence = lead.get("follow_up_sequence") or []

    flat = {
        "id": lead.get("id", ""),
        "company_name": lead.get("company_name", ""),
        "website": lead.get("website", ""),
        "industry": lead.get("industry", ""),
        "size": lead.get("size", ""),
        "location": lead.get("location", ""),
        "address": lead.get("address", ""),
        "phone": lead.get("phone", ""),
        "contact_emails": "; ".join(lead.get("contact_emails") or []),
        "decision_maker_name": lead.get("decision_maker_name", ""),
        "decision_maker_title": lead.get("decision_maker_title", ""),
        "decision_maker_linkedin": lead.get("decision_maker_linkedin", ""),
        "decision_makers": "; ".join(lead.get("decision_makers") or []),
        "pain_points": "; ".join(lead.get("pain_points") or []),
        "qualification_score": lead.get("qualification_score", ""),
        "qualification_reason": lead.get("qualification_reason", ""),
        "status": lead.get("status", ""),
        "current_hr_tools": "; ".join(lead.get("tech_stack", {}).get("current_tools", [])),
        "tech_maturity": lead.get("tech_stack", {}).get("maturity", ""),
        "pitch_angle": lead.get("tech_stack", {}).get("pitch_angle", ""),
        "email_subject": outreach.get("subject", ""),
        "email_body_day1": outreach.get("email_body", ""),
        "followup_day3": sequence[0].get("email_body", "") if len(sequence) > 0 else "",
        "followup_day7": sequence[1].get("email_body", "") if len(sequence) > 1 else "",
        "followup_day14": sequence[2].get("email_body", "") if len(sequence) > 2 else "",
    }
    return flat


def push_to_webhook(lead: Dict) -> bool:
    """POST flattened lead data to the configured CRM webhook URL."""
    webhook_url = settings.crm_webhook_url
    if not webhook_url:
        logger.debug(f"[CRM] No webhook configured — skipping push for {lead.get('company_name')}")
        return True  # no-op, not an error

    payload = _flatten_lead(lead)
    try:
        resp = requests.post(
            webhook_url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        resp.raise_for_status()
        logger.info(f"[CRM] Pushed lead to webhook: {lead.get('company_name')} → {resp.status_code}")
        return True
    except Exception as e:
        logger.warning(f"[CRM] Webhook push failed for {lead.get('company_name')}: {e}")
        return False


def push_to_google_sheets(lead: Dict) -> bool:
    """Append a lead row to a Google Sheet."""
    sheets_id = settings.google_sheets_id
    service_account_json = settings.google_service_account_json

    if not sheets_id or not service_account_json:
        logger.debug("[CRM] Google Sheets not configured — skipping")
        return True  # no-op

    try:
        import gspread
        from google.oauth2.service_account import Credentials

        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        creds_dict = json.loads(service_account_json)
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        gc = gspread.authorize(creds)
        sh = gc.open_by_key(sheets_id)
        ws = sh.sheet1

        # If sheet is empty, write header row first
        if ws.row_count == 0 or not ws.row_values(1):
            flat = _flatten_lead(lead)
            ws.append_row(list(flat.keys()))

        flat = _flatten_lead(lead)
        ws.append_row(list(flat.values()))
        logger.info(f"[CRM] Appended to Google Sheets: {lead.get('company_name')}")
        return True
    except ImportError:
        logger.warning("[CRM] gspread not installed — run: pip install gspread google-auth")
        return False
    except Exception as e:
        logger.warning(f"[CRM] Google Sheets push failed: {e}")
        return False


def push_lead_to_crm(lead: Dict) -> bool:
    """
    Push an approved lead to all configured CRM backends.
    Called after a lead is approved (Slack button or dashboard approve).
    Never raises — always logs and returns success/failure.
    """
    company = lead.get("company_name", "Unknown")

    if not settings.crm_webhook_url and not settings.google_sheets_id:
        logger.info(
            f"[CRM no-op] Lead '{company}' ready for CRM — "
            f"set CRM_WEBHOOK_URL or GOOGLE_SHEETS_ID in .env to enable push"
        )
        return True

    webhook_ok = push_to_webhook(lead)
    sheets_ok = push_to_google_sheets(lead)
    return webhook_ok and sheets_ok
