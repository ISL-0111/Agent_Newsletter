"""
LangGraph 그래프 정의
노드와 엣지를 연결해 전체 에이전트 흐름을 구성한다.
"""
from langgraph.graph import StateGraph, END
from agents.state import AgentState
from nodes.nodes import (
    ingest_node,
    command_router_node,
    prefilter_node,
    classifier_node,
    vision_node,
    crawler_node,
    summarizer_node,
    embed_node,
    formatter_node,
    telegram_sender_node,
    search_handler_node,
    error_handler_node,
)


def route_after_command(state: AgentState) -> str:
    """Command Router 이후 분기"""
    trigger = state.get("trigger")
    if trigger == "schedule":
        return "ingest"

    action = state.get("user_intent", {}).get("action", "unknown")
    routes = {
        "summary":  "ingest",
        "search":   "search_handler",
        "resend":   "search_handler",
        "status":   "formatter",
        "skip":     "formatter",
        "settings": "formatter",
        "unknown":  "telegram_sender",
    }
    return routes.get(action, "telegram_sender")


def route_after_classifier(state: AgentState) -> str:
    """Classifier 이후 단일 경로 라우팅"""
    types = {item["content_type"] for item in state["mail_items"]}
    if "image_only" in types:
        return "vision"
    if "excerpt_with_link" in types:
        return "crawler"
    return "summarizer"


def build_graph() -> StateGraph:
    graph = StateGraph(AgentState)

    # 노드 등록
    graph.add_node("command_router",  command_router_node)
    graph.add_node("ingest",          ingest_node)
    graph.add_node("prefilter",       prefilter_node)
    graph.add_node("classifier",      classifier_node)
    graph.add_node("vision",          vision_node)
    graph.add_node("crawler",         crawler_node)
    graph.add_node("summarizer",      summarizer_node)
    graph.add_node("embed",           embed_node)
    graph.add_node("formatter",       formatter_node)
    graph.add_node("telegram_sender", telegram_sender_node)
    graph.add_node("search_handler",  search_handler_node)
    graph.add_node("error_handler",   error_handler_node)

    # 시작점
    graph.set_entry_point("command_router")

    # Command Router → 분기 (추가됨)
    graph.add_conditional_edges(
        "command_router",
        route_after_command,
        {
            "ingest":          "ingest",
            "search_handler":  "search_handler",
            "formatter":       "formatter",
            "telegram_sender": "telegram_sender",
        }
    )

    # Ingest → PreFilter → Classifier
    graph.add_edge("ingest",    "prefilter")
    graph.add_edge("prefilter", "classifier")

    # Classifier → Vision / Crawler / Summarizer (중복 제거)
    graph.add_conditional_edges(
        "classifier",
        route_after_classifier,
        {
            "vision":     "vision",
            "crawler":    "crawler",
            "summarizer": "summarizer",
        }
    )

    # Vision / Crawler → Summarizer
    graph.add_edge("vision",  "summarizer")
    graph.add_edge("crawler", "summarizer")

    # Summarizer → Embed → Formatter → Sender → END
    graph.add_edge("summarizer",      "embed")
    graph.add_edge("embed",           "formatter")
    graph.add_edge("formatter",       "telegram_sender")
    graph.add_edge("telegram_sender", END)

    # 검색 경로
    graph.add_edge("search_handler",  "telegram_sender")

    # 오류 경로
    graph.add_edge("error_handler",   "telegram_sender")

    return graph.compile()


# 컴파일된 그래프 (앱 전체에서 재사용)
agent = build_graph()