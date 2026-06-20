"""
Supervisor Graph (LangGraph)
----------------------------
Orchestrates the 3 agents using a StateGraph with conditional routing.

Pattern: Supervisor (central orchestrator decides which agent runs next)
by reading the `next` field from shared LeadState.

Flow:
  [START] → research_agent
                ↓ (leads found?)
          qualification_agent
           /              \
    (score >= threshold)  (score < threshold)
          ↓                ↓
     sales_agent         [END]
          ↓
        [END]
"""
import uuid
from loguru import logger
from langgraph.graph import StateGraph, END
from graph.state import LeadState
from agents.research_agent import research_agent
from agents.qualification_agent import qualification_agent
from agents.sales_agent import sales_agent
from core.config import get_settings
from core.logging import setup_logging

setup_logging()
settings = get_settings()


def route(state: LeadState) -> str:
    """
    Supervisor routing function. Reads state.next to decide next node.
    Circuit breaker: hard-stop if iteration limit exceeded.
    """
    next_node = state.get("next", "END")

    if state.get("iteration", 0) > settings.max_iterations:
        logger.bind(agent="supervisor", correlation_id=state.get("correlation_id", "?")).warning(
            "Max iterations exceeded, circuit breaker triggered"
        )
        return END

    mapping = {
        "qualify": "qualification_agent",
        "sales": "sales_agent",
    }
    return mapping.get(next_node, END)


def build_graph() -> StateGraph:
    """Construct and compile the LangGraph supervisor graph."""
    graph = StateGraph(LeadState)

    graph.add_node("research_agent", research_agent)
    graph.add_node("qualification_agent", qualification_agent)
    graph.add_node("sales_agent", sales_agent)

    graph.set_entry_point("research_agent")

    graph.add_conditional_edges(
        "research_agent",
        route,
        {"qualification_agent": "qualification_agent", END: END},
    )
    graph.add_conditional_edges(
        "qualification_agent",
        route,
        {"sales_agent": "sales_agent", END: END},
    )
    graph.add_edge("sales_agent", END)

    return graph.compile()


def run_pipeline(
    keyword: str,
    max_leads: int = None,
    run_id: str = None,
    country: str = None,
    region: str = None,
    exclude_with_hrms: bool = True,
    mode: str = "discover",
    fast: bool = True,
) -> LeadState:
    """
    Entry point: run the full lead generation pipeline.
    Generates a correlation_id that flows through all agent logs.

    max_leads: cap on how many leads to process (overrides config default).
    run_id:    Theater stream id (the pollable job id). Agents emit live events
               keyed by this id; falls back to correlation_id when not provided.
    """
    correlation_id = str(uuid.uuid4())[:8]
    log = logger.bind(agent="supervisor", correlation_id=correlation_id)

    graph = build_graph()

    initial_state: LeadState = {
        "keyword": keyword,
        "leads": [],
        "messages": [],
        "next": "research",
        "iteration": 0,
        "errors": [],
        "correlation_id": correlation_id,
        "max_leads": max_leads or settings.max_leads_per_run,
        "run_id": run_id or correlation_id,
        "country": country,
        "region": region,
        "exclude_with_hrms": exclude_with_hrms,
        "mode": mode,
        "fast": fast,
    }

    log.info(f"Pipeline START | keyword='{keyword}' max_leads={initial_state['max_leads']}")

    final_state = graph.invoke(initial_state)

    # Signal the Live Agent Theater that the run is complete.
    try:
        from observability.event_bus import emit
        emit(initial_state["run_id"], "done", agent="supervisor", stage="done",
             message="Pipeline complete")
    except Exception:
        pass

    qualified = sum(1 for l in final_state["leads"] if l.get("status") in ("outreach_ready", "pending_review"))
    disqualified = sum(1 for l in final_state["leads"] if l.get("status") == "disqualified")

    log.info(
        f"Pipeline COMPLETE | total={len(final_state['leads'])} "
        f"qualified={qualified} disqualified={disqualified}"
    )

    return final_state
