"""Construcción del grafo LangGraph.

Flujo:
    router ──(chat)──▶ conversational ──▶ END
           └─(analyze)▶ extract ──▶ geocode(en extract) ──▶ fan-out
                            ├── fetch_pois ─────────────┐
                            ├── fetch_crime ────────────┤
                            └── query_planner ▶ tavily_researcher
                                                        │ (fan-in)
                                                        ▼
                                                   synthesizer ──▶ END
"""
from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from app.nodes.conversational import conversational
from app.nodes.extract import extract
from app.nodes.fetch_crime import fetch_crime
from app.nodes.fetch_pois import fetch_pois
from app.nodes.query_planner import query_planner
from app.nodes.router import route_intent, router
from app.nodes.synthesizer import synthesizer
from app.nodes.tavily_researcher import tavily_researcher
from app.state import GraphState


def build_graph():
    g = StateGraph(GraphState)

    g.add_node("router", router)
    g.add_node("conversational", conversational)
    g.add_node("extract", extract)
    g.add_node("fetch_pois", fetch_pois)
    g.add_node("fetch_crime", fetch_crime)
    g.add_node("query_planner", query_planner)
    g.add_node("tavily_researcher", tavily_researcher)
    g.add_node("synthesizer", synthesizer)

    g.add_edge(START, "router")
    g.add_conditional_edges(
        "router",
        route_intent,
        {"conversational": "conversational", "extract": "extract"},
    )
    g.add_edge("conversational", END)

    # fan-out desde extract a las dos ramas (paralelas)
    g.add_edge("extract", "fetch_pois")
    g.add_edge("extract", "fetch_crime")
    g.add_edge("extract", "query_planner")
    g.add_edge("query_planner", "tavily_researcher")

    # fan-in: synthesizer espera a las tres entradas antes de ejecutarse
    g.add_edge("fetch_pois", "synthesizer")
    g.add_edge("fetch_crime", "synthesizer")
    g.add_edge("tavily_researcher", "synthesizer")
    g.add_edge("synthesizer", END)

    return g.compile()


# Instancia reutilizable
graph = build_graph()
