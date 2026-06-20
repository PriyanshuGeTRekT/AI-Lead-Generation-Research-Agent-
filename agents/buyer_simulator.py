"""
Buyer Simulation & Email Arena
------------------------------
Before a single email is sent, an LLM role-plays the prospect's actual decision
maker and "receives" the outreach. It scores reply-likelihood, predicts the
reaction and top objection, then the sales agent runs a self-play A/B: it writes
a sharper Variant B, simulates both, and ships the winner.

One LLM call does the whole arena (write B + evaluate A & B as the buyer) to keep
latency/cost bounded. Fail-safe: returns None so the sales agent keeps Variant A.
"""
import json
from typing import Optional

ARENA_PROMPT = """You are simulating a B2B buyer to pressure-test cold outreach for HumanMaximizer (an HRMS software company).

The prospect's decision maker:
{persona_info}

VARIANT A (already written) — subject and body:
SUBJECT: {a_subject}
BODY:
{a_body}

Do TWO things:
1) Write a SHARPER "Variant B": shorter, more specific to this company's pain, with a lower-friction ask. Same sender sign-off style.
2) ROLE-PLAY the decision maker reading each variant in a busy inbox. For each, judge honestly: reply likelihood (0-1), the predicted reaction (one sentence, first-person-ish observation), their top objection, and overall sentiment (positive/neutral/negative). Real buyers ignore generic pitches and reward specificity + proof.

Respond with JSON ONLY:
{{
  "persona_summary": "...(2 sentences: who they are, what they care about, how they treat cold email)",
  "variants": [
    {{"variant": "A", "subject": {a_subject_json}, "email_body": "...(echo Variant A body)", "reply_likelihood": <0-1>, "predicted_reaction": "...", "top_objection": "...", "sentiment": "positive|neutral|negative"}},
    {{"variant": "B", "subject": "...", "email_body": "...(your Variant B)", "reply_likelihood": <0-1>, "predicted_reaction": "...", "top_objection": "...", "sentiment": "positive|neutral|negative"}}
  ],
  "winner": "A" or "B",
  "uplift": <percentage-point reply-likelihood gap between winner and loser, 0-100>
}}"""


def _clamp01(n) -> float:
    try:
        return max(0.0, min(1.0, float(n)))
    except (TypeError, ValueError):
        return 0.0


def simulate_arena(
    agent,
    lead: dict,
    base_subject: str,
    base_body: str,
) -> Optional[dict]:
    """Run the email arena. Returns a normalized BuyerSimulation dict or None."""
    try:
        dm = lead.get("decision_maker_full_name") or lead.get("decision_maker_name") or "the HR lead"
        persona_info = json.dumps(
            {
                "name": dm,
                "title": lead.get("decision_maker_title") or "HR decision maker",
                "company": lead.get("company_name"),
                "industry": lead.get("industry"),
                "size": lead.get("size"),
                "location": lead.get("location"),
                "pain_points": lead.get("pain_points"),
                "current_hr_stack": (lead.get("tech_stack") or {}).get("current_tools"),
            },
            indent=2,
        )
        prompt = ARENA_PROMPT.format(
            persona_info=persona_info,
            a_subject=base_subject,
            a_subject_json=json.dumps(base_subject or ""),
            a_body=base_body,
        )
        raw = agent.call_llm(prompt, temperature=0.5, max_tokens=900, use_cache=False)
        data = agent.parse_json_response(raw)

        variants = []
        for v in data.get("variants", []):
            tag = str(v.get("variant", "")).upper().strip() or "A"
            sentiment = str(v.get("sentiment", "neutral")).lower()
            if sentiment not in ("positive", "neutral", "negative"):
                sentiment = "neutral"
            variants.append(
                {
                    "variant": tag,
                    "subject": str(v.get("subject", "")).strip(),
                    "email_body": str(v.get("email_body", "")).strip(),
                    "reply_likelihood": round(_clamp01(v.get("reply_likelihood", 0)), 2),
                    "predicted_reaction": str(v.get("predicted_reaction", "")).strip(),
                    "top_objection": str(v.get("top_objection", "")).strip(),
                    "sentiment": sentiment,
                }
            )
        if len(variants) < 2:
            return None

        # Determine winner from likelihoods (trust the model, but verify).
        winner = max(variants, key=lambda v: v["reply_likelihood"])["variant"]
        if str(data.get("winner", "")).upper() in ("A", "B"):
            winner = str(data["winner"]).upper()
        likes = sorted((v["reply_likelihood"] for v in variants), reverse=True)
        uplift = round((likes[0] - likes[1]) * 100, 1) if len(likes) >= 2 else 0.0

        return {
            "persona_summary": str(data.get("persona_summary", "")).strip(),
            "winner": winner,
            "uplift": uplift,
            "variants": variants,
        }
    except Exception:
        return None
