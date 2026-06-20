"""
Chat Agent (24/7 inbound qualifier)
-----------------------------------
Powers the website chat widget: answers HR-software questions as "Maxi" for
HumanMaximizer, and gently qualifies the visitor (company size, current HR
process, name + work email). Uses the active LLM provider via BaseAgent.

Grounded in product context from the hcmv3 repo / RAG when available; otherwise a
concise built-in description. Fail-safe: returns a friendly fallback on error.
"""
from agents.base import BaseAgent

_SYSTEM = """You are "Maxi", the friendly assistant for HumanMaximizer — an Indian HRMS
(human resource management software) for SMEs: attendance, payroll, leave, onboarding,
compliance, and performance, mobile-first and quick to roll out.

Your goals, in order:
1. Be genuinely helpful — answer the visitor's HR / HR-software question plainly.
2. Gently qualify: find out their company size, current HR process (Excel? another HRMS?),
   and biggest HR pain. Ask ONE question at a time, conversationally.
3. If they show interest, capture their name and WORK email to book a quick demo.

Rules: keep replies under 80 words. Warm, peer-to-peer, no jargon, no hype words
("revolutionary", "seamless", "synergy"). India context (₹, Indian compliance like PF/ESI/PT).
Never invent features or pricing — if unsure, offer to connect them with the team."""


class ChatAgent(BaseAgent):
    name = "chat_agent"

    def run(self, state: dict) -> dict:  # unused (not a pipeline node)
        return state

    def reply(self, messages: list[dict]) -> str:
        convo = "\n".join(
            f"{(m.get('role') or 'user').capitalize()}: {m.get('content', '')}"
            for m in (messages or [])[-10:]
        )
        prompt = f"{_SYSTEM}\n\nConversation so far:\n{convo}\n\nMaxi:"
        return self.call_llm(prompt, temperature=0.5, max_tokens=220, use_cache=False).strip()


def chat_reply(messages: list[dict]) -> str:
    try:
        return ChatAgent().reply(messages)
    except Exception:
        return (
            "I'm having a little trouble connecting right now — but I'd love to help. "
            "Could you share your company size and how you currently manage HR (Excel, "
            "another tool, or manually)?"
        )
