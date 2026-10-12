"""
rag/diagnostic_graph.py

Builds a symptom -> component -> root_cause -> solution graph per tenant
from the same flat "H1: val1 | H2: val2" row text already produced by
DoclingParser._parse_tabular, and supports traversal queries against it.

This does NOT change ingestion/parsers/docling_parser.py or chunker.py.
It reads back what's already in Qdrant, the same way HybridRetriever
.rebuild_bm25() does via qdrant_store.get_all_texts().
"""
from __future__ import annotations

import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field

import networkx as nx

logger = logging.getLogger(__name__)

# Column-name keyword heuristics, same style as DoclingParser._is_reference_sheet.
# First match wins; extend per-domain by editing these lists (or later, move
# to tenant config once config/tenants/*.yaml exists).
ROLE_KEYWORDS: dict[str, list[str]] = {
    "symptom": ["symptom", "description", "fault", "error_desc", "issue", "problem"],
    "component": ["component", "part", "assembly", "subsystem", "equipment_part"],
    "root_cause": ["root_cause", "rootcause", "cause"],
    "solution": ["solution", "resolution", "corrective_action", "fix", "remedy"],
    "error_code": ["error_code", "errorcode", "fault_code", "code"],
    "machine": ["machine", "machine_id", "asset", "equipment_id", "unit"],
}

ROW_FIELD_RE = re.compile(r"([^|]+?):\s*([^|]+?)(?=\s*\||$)")


@dataclass
class GraphNode:
    role: str
    label: str
    chunk_ids: set[str] = field(default_factory=set)


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def _classify_header(header: str) -> str | None:
    h = header.strip().lower()
    for role, keywords in ROLE_KEYWORDS.items():
        if any(kw in h for kw in keywords):
            return role
    return None


def _parse_row_fields(text: str) -> dict[str, str]:
    """Recover the {header: value} pairs from a row chunk's flat text.
    Handles the "[Sheet: X] H1: v1 | H2: v2" shape produced by
    DoclingParser._parse_tabular / the plain CSV "H: v | H: v" shape."""
    text = re.sub(r"^\[Sheet:[^\]]*\]\s*", "", text)
    fields: dict[str, str] = {}
    for match in ROW_FIELD_RE.finditer(text):
        header, value = match.group(1).strip(), match.group(2).strip()
        if header and value:
            fields[header] = value
    return fields


class DiagnosticGraph:
    """Thin wrapper around a per-tenant nx.MultiDiGraph."""

    def __init__(self, tenant_id: str, graph: nx.MultiDiGraph | None = None):
        self.tenant_id = tenant_id
        self.graph = graph if graph is not None else nx.MultiDiGraph()

    # ---- node/edge helpers -------------------------------------------------

    def _node_id(self, role: str, label: str) -> str:
        return f"{role}:{_normalize(label)}"

    def _ensure_node(self, role: str, label: str, chunk_id: str) -> str:
        nid = self._node_id(role, label)
        if nid not in self.graph:
            self.graph.add_node(nid, role=role, label=label, chunk_ids=[chunk_id])
        else:
            cids = self.graph.nodes[nid].setdefault("chunk_ids", [])
            if chunk_id not in cids:
                cids.append(chunk_id)
        return nid

    def _add_edge(self, src: str, dst: str, relation: str, chunk_id: str) -> None:
        existing = self.graph.get_edge_data(src, dst)
        for _, data in (existing or {}).items():
            if data.get("relation") == relation:
                data["weight"] = data.get("weight", 1) + 1
                if chunk_id not in data.get("chunk_ids", []):
                    data.setdefault("chunk_ids", []).append(chunk_id)
                return
        self.graph.add_edge(src, dst, relation=relation, weight=1, chunk_ids=[chunk_id])

    # ---- build ---------------------------------------------------------------

    def add_record(self, chunk_id: str, fields: dict[str, str]) -> bool:
        """Add one incident row's edges. Returns True if it contributed
        anything (i.e. at least a symptom+component or component+root_cause
        pair was found — rows with no recognizable roles are skipped)."""
        by_role: dict[str, str] = {}
        for header, value in fields.items():
            role = _classify_header(header)
            if role:
                by_role[role] = value

        if not by_role:
            return False

        nodes = {role: self._ensure_node(role, val, chunk_id) for role, val in by_role.items()}

        added = False
        if "symptom" in nodes and "component" in nodes:
            self._add_edge(nodes["symptom"], nodes["component"], "observed_on", chunk_id)
            added = True
        if "component" in nodes and "root_cause" in nodes:
            self._add_edge(nodes["component"], nodes["root_cause"], "caused_by", chunk_id)
            added = True
        if "root_cause" in nodes and "solution" in nodes:
            self._add_edge(nodes["root_cause"], nodes["solution"], "resolved_by", chunk_id)
            added = True
        # symptom with no component but a direct root_cause (sparser sheets)
        if "symptom" in nodes and "component" not in nodes and "root_cause" in nodes:
            self._add_edge(nodes["symptom"], nodes["root_cause"], "caused_by", chunk_id)
            added = True
        return added

    # ---- query -----------------------------------------------------------

    def match_symptom_nodes(self, query: str, top_k: int = 3) -> list[str]:
        """Token-overlap match against symptom nodes (cheap, no embedding
        dependency here — this graph is a structural signal alongside,
        not instead of, the hybrid retriever)."""
        q_tokens = set(re.findall(r"\w+", query.lower()))
        scored = []
        for nid, data in self.graph.nodes(data=True):
            if data.get("role") != "symptom":
                continue
            n_tokens = set(re.findall(r"\w+", data["label"].lower()))
            overlap = len(q_tokens & n_tokens)
            if overlap:
                scored.append((overlap, nid))
        scored.sort(reverse=True)
        return [nid for _, nid in scored[:top_k]]

    def trace_from_symptom(self, symptom_node_id: str, max_depth: int = 3) -> list[dict]:
        """Walk symptom -> component -> root_cause -> solution, returning
        each path ranked by the minimum edge weight along it (a path only
        as strong as its weakest, least-repeated link)."""
        # Manual BFS since we don't have a fixed target node (networkx's
        # simple-path helpers require one).
        paths: list[dict] = []
        frontier = [(symptom_node_id, [], float("inf"))]
        for _ in range(max_depth):
            next_frontier = []
            for node, trail, min_w in frontier:
                out_edges = self.graph.out_edges(node, data=True, keys=True)
                if not out_edges:
                    if trail:
                        paths.append(self._path_to_dict(symptom_node_id, trail, min_w))
                    continue
                for u, v, k, data in out_edges:
                    new_trail = trail + [(u, v, data)]
                    next_frontier.append((v, new_trail, min(min_w, data["weight"])))
            if not next_frontier:
                break
            frontier = next_frontier
        for node, trail, min_w in frontier:
            if trail:
                paths.append(self._path_to_dict(symptom_node_id, trail, min_w))

        seen = set()
        unique = []
        for p in sorted(paths, key=lambda p: p["confidence_weight"], reverse=True):
            key = tuple(n["label"] for n in p["nodes"])
            if key not in seen:
                seen.add(key)
                unique.append(p)
        return unique

    def _path_to_dict(self, start: str, trail: list[tuple], min_w: int) -> dict:
        nodes = [self.graph.nodes[start]]
        chunk_ids: set[str] = set(self.graph.nodes[start].get("chunk_ids", []))
        for _, v, data in trail:
            nodes.append(self.graph.nodes[v])
            chunk_ids.update(data.get("chunk_ids", []))
        return {
            "nodes": [{"role": n["role"], "label": n["label"]} for n in nodes],
            "confidence_weight": min_w if min_w != float("inf") else 0,
            "chunk_ids": sorted(chunk_ids),
        }

    def query(self, symptom_query: str, top_k_symptoms: int = 3, max_depth: int = 3) -> list[dict]:
        results: list[dict] = []
        for nid in self.match_symptom_nodes(symptom_query, top_k_symptoms):
            results.extend(self.trace_from_symptom(nid, max_depth))
        results.sort(key=lambda p: p["confidence_weight"], reverse=True)
        return results

    # ---- serialization (for storage/graph_store.py) -----------------------

    def to_dict(self) -> dict:
        return nx.node_link_data(self.graph, edges="edges")

    @classmethod
    def from_dict(cls, tenant_id: str, data: dict) -> "DiagnosticGraph":
        graph = nx.node_link_graph(data, edges="edges", multigraph=True, directed=True)
        return cls(tenant_id, graph)


def build_from_rows(tenant_id: str, rows: list[tuple[str, dict]]) -> DiagnosticGraph:
    """rows: same shape as QdrantStore.get_all_texts() -> [(chunk_id, payload)]"""
    dg = DiagnosticGraph(tenant_id)
    contributed = 0
    for chunk_id, payload in rows:
        text = payload.get("text", "")
        if not text:
            continue
        fields = _parse_row_fields(text)
        if fields and dg.add_record(chunk_id, fields):
            contributed += 1
    logger.info(
        "Built diagnostic graph for tenant %s: %d nodes, %d edges (%d/%d rows contributed)",
        tenant_id,
        dg.graph.number_of_nodes(),
        dg.graph.number_of_edges(),
        contributed,
        len(rows),
    )
    return dg
