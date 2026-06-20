"""
Adversarial Qualification Debate
--------------------------------
Instead of a single LLM emitting one score, three personas argue each lead over
two rounds and converge on a consensus. This makes scoring more robust (the
Skeptic catches over-eager Champion calls) and produces an explainable transcript.

  • The Champion  — argues FOR pursuing the lead (upside, triggers, access)
  • The Skeptic   — argues AGAINST (switching cost, budget/timing, fit gaps)
  • The ICP Analyst — weighs both against the ideal customer profile

The whole debate runs in ONE structured LLM call (cost/latency-bounded) that
returns the full transcript + consensus. Fail-safe: returns None on any error so
the caller falls back to the existing single-LLM score.
"""
import json
from typing import Optional

DEBATE_PROMPT = """You are running an internal sales-qualification DEBATE for HumanMaximizer, an HRMS software company, about whether to pursue a prospect.

Product knowledge (use ONLY this, do not invent features):
{rag_context}

Prospect:
{lead_info}

Simulate a rigorous 2-round debate between three personas, each scoring 0-10:
- "champion": argues FOR pursuing (buying triggers, workforce pain, decision-maker access, upside).
- "skeptic": argues AGAINST (incumbent tooling / switching cost, budget & timing risk, weak fit, procurement drag).
- "analyst": weighs both against the ideal customer profile (size 10-1000, workforce-heavy industry, manual/legacy HR, identified DM) and stays neutral.

CRITICAL: If the company SELLS HR/HRMS/payroll software it is a COMPETITOR — all personas score 1 and the verdict is "disqualify (competitor)".

Respond with JSON ONLY in this exact shape:
{{
  "transcript": [
    {{"persona": "champion", "round": 1, "argument": "...", "score": <0-10>}},
    {{"persona": "skeptic", "round": 1, "argument": "...", "score": <0-10>}},
    {{"persona": "analyst", "round": 1, "argument": "...", "score": <0-10>}},
    {{"persona": "champion", "round": 2, "argument": "...", "score": <0-10>}},
    {{"persona": "skeptic", "round": 2, "argument": "...", "score": <0-10>}},
    {{"persona": "analyst", "round": 2, "argument": "...", "score": <0-10>}}
  ],
  "consensus_score": <0-10 float, the reconciled final score>,
  "confidence": <0-1 float, higher when the three personas agree>,
  "verdict": "...(one sentence: pursue / nurture / disqualify and why)"
}}
Each argument must be one concise, specific sentence grounded in the prospect's data."""


def _clamp(n: float, lo: float, hi: float) -> float:
    try:
        return max(lo, min(hi, float(n)))
    except (TypeError, ValueError):
        return lo


def debate_qualify(agent, lead: dict, rag_context: str) -> Optional[dict]:
    """
    Run the debate via the agent's LLM wrapper. Returns a normalized dict:
      {consensus_score, confidence, rounds, transcript, verdict}
    or None if anything goes wrong (caller should fall back).
    """
    try:
        lead_info = json.dumps(
            {
                "company_name": lead.get("company_name"),
                "industry": lead.get("industry"),
                "size": lead.get("size"),
                "location": lead.get("location"),
                "description": lead.get("description"),
                "pain_points": lead.get("pain_points"),
                "tech_stack": lead.get("tech_stack"),
                "hrms_verdict": lead.get("hrms"),
                "predicted_fit": lead.get("lead_score"),
                "decision_maker_title": lead.get("decision_maker_title"),
            },
            indent=2,
        )
        prompt = DEBATE_PROMPT.format(rag_context=rag_context, lead_info=lead_info)
        raw = agent.call_llm(prompt, temperature=0.3, max_tokens=900, use_cache=False)
        data = agent.parse_json_response(raw)

        transcript = []
        for t in data.get("transcript", []):
            persona = str(t.get("persona", "analyst")).lower()
            if persona not in ("champion", "skeptic", "analyst"):
                persona = "analyst"
            transcript.append(
                {
                    "persona": persona,
                    "round": int(t.get("round", 1) or 1),
                    "argument": str(t.get("argument", "")).strip(),
                    "score": round(_clamp(t.get("score", 5), 0, 10), 1),
                }
            )
        if not transcript:
            return None

        rounds = max((t["round"] for t in transcript), default=1)
        consensus = data.get("consensus_score")
        if consensus is None:
            finals = [t["score"] for t in transcript if t["round"] == rounds]
            consensus = sum(finals) / len(finals) if finals else 5.0
        consensus = round(_clamp(consensus, 0, 10), 1)

        confidence = data.get("confidence")
        if confidence is None:
            scores = [t["score"] for t in transcript]
            spread = (max(scores) - min(scores)) if scores else 0
            confidence = 1 - spread / 10
        confidence = round(_clamp(confidence, 0, 1), 2)

        return {
            "consensus_score": consensus,
            "confidence": confidence,
            "rounds": rounds,
            "transcript": transcript,
            "verdict": str(data.get("verdict", "")).strip()
            or ("pursue" if consensus >= 5 else "nurture"),
        }
    except Exception:
        return None
