"""Explicit tools available to the retrieval agent."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Awaitable, Callable

from models.schemas import RetrievedChunk


@dataclass
class ToolResult:
    tool_name: str
    chunks: list[RetrievedChunk] = field(default_factory=list)
    graph_matches: list[dict] = field(default_factory=list)
    summary: str = ""


class RetrievalToolbox:
    """Small, auditable tool layer between the agent and retrieval services."""

    def __init__(self, retriever, graph_store=None):
        self.retriever = retriever
        self.graph_store = graph_store
        self._tools: dict[str, Callable[[str], Awaitable[ToolResult]]] = {
            "search_knowledge_base": self.search_knowledge_base,
            "search_error_code": self.search_error_code,
            "search_diagnostic_graph": self.search_diagnostic_graph,
        }

    @property
    def descriptions(self) -> str:
        return (
            "- search_knowledge_base: semantic + keyword search across all ingested documents\n"
            "- search_error_code: targeted search for an alarm, error, or incident code\n"
            "- search_diagnostic_graph: find symptom/equipment/cause relationships from incident history"
        )

    async def call(self, name: str, query: str) -> ToolResult:
        tool = self._tools.get(name)
        if tool is None:
            raise ValueError(f"Unknown retrieval tool: {name}")
        return await tool(query)

    async def search_knowledge_base(self, query: str) -> ToolResult:
        chunks = await self.retriever.retrieve_across_all(query)
        return ToolResult(
            tool_name="search_knowledge_base",
            chunks=chunks,
            summary=f"semantic and keyword search returned {len(chunks)} result(s)",
        )

    async def search_error_code(self, query: str) -> ToolResult:
        chunks = await self.retriever.retrieve_across_all(
            f"error code alarm code incident code {query}"
        )
        return ToolResult(
            tool_name="search_error_code",
            chunks=chunks,
            summary=f"error-code search returned {len(chunks)} result(s)",
        )

    async def search_diagnostic_graph(self, query: str) -> ToolResult:
        if self.graph_store is None:
            return ToolResult(tool_name="search_diagnostic_graph", summary="diagnostic graph unavailable")

        matches: list[dict] = []
        for tenant_id in self.retriever.qdrant_store.list_tenant_ids():
            graph = self.graph_store.ensure(tenant_id, self.retriever.qdrant_store)
            matches.extend(graph.query(query, top_k_symptoms=3, max_depth=3))
        matches.sort(key=lambda item: item.get("confidence_weight", 0), reverse=True)
        return ToolResult(
            tool_name="search_diagnostic_graph",
            graph_matches=matches[:5],
            summary=f"diagnostic graph returned {len(matches[:5])} relationship(s)",
        )

