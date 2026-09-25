import networkx as nx

PROCESS_FLOW = [
    ("deposition",  "cmp"),
    ("cmp",         "lithography"),
    ("lithography", "etching"),
    ("etching",     "wet_clean"),
    ("wet_clean",   "diffusion"),
    ("diffusion",   "inspection"),
    ("inspection",  "metrology"),
]

STEP_METADATA = {
    "deposition":  {"risk_level": "medium", "description": "Thin film material deposition"},
    "cmp":         {"risk_level": "medium", "description": "Chemical mechanical planarization"},
    "lithography": {"risk_level": "high",   "description": "Pattern transfer via light exposure"},
    "etching":     {"risk_level": "high",   "description": "Material removal via chemical/plasma"},
    "wet_clean":   {"risk_level": "medium", "description": "Chemical cleaning to remove etch residues"},
    "diffusion":   {"risk_level": "low",    "description": "Dopant introduction via heat"},
    "inspection":  {"risk_level": "low",    "description": "Defect detection and measurement"},
    "metrology":   {"risk_level": "low",    "description": "Dimensional measurement and verification"},
}

_graph = None


def get_graph() -> nx.DiGraph:
    global _graph
    if _graph is None:
        _graph = nx.DiGraph()
        for step, metadata in STEP_METADATA.items():
            _graph.add_node(step, **metadata)
        for src, dst in PROCESS_FLOW:
            _graph.add_edge(src, dst, relationship="feeds_into")
    return _graph


def get_upstream_steps(step: str, depth: int = 2) -> list[dict]:
    """Return upstream steps within given depth — potential root cause candidates."""
    graph = get_graph()
    if step not in graph:
        return []

    upstream = []
    visited = set()
    queue = [(step, 0)]

    while queue:
        current, current_depth = queue.pop(0)
        if current_depth >= depth:
            continue
        for predecessor in graph.predecessors(current):
            if predecessor not in visited:
                visited.add(predecessor)
                node_data = graph.nodes[predecessor]
                upstream.append({
                    "step": predecessor,
                    "distance": current_depth + 1,
                    "risk_level": node_data.get("risk_level", "unknown"),
                    "description": node_data.get("description", ""),
                })
                queue.append((predecessor, current_depth + 1))

    risk_order = {"high": 0, "medium": 1, "low": 2, "unknown": 3}
    upstream.sort(key=lambda x: risk_order[x["risk_level"]])
    return upstream


def get_downstream_impact(step: str, depth: int = 2) -> list[dict]:
    """Return downstream steps impacted if this step has a defect."""
    graph = get_graph()
    if step not in graph:
        return []

    downstream = []
    visited = set()
    queue = [(step, 0)]

    while queue:
        current, current_depth = queue.pop(0)
        if current_depth >= depth:
            continue
        for successor in graph.successors(current):
            if successor not in visited:
                visited.add(successor)
                node_data = graph.nodes[successor]
                downstream.append({
                    "step": successor,
                    "distance": current_depth + 1,
                    "risk_level": node_data.get("risk_level", "unknown"),
                    "description": node_data.get("description", ""),
                })
                queue.append((successor, current_depth + 1))

    return downstream
