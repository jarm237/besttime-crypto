"""
Causal Graph Analysis - Parse, analyze, and traverse causal relationships.

Provides graph query methods, path finding, and causal inference capabilities.
"""

import json
from typing import Dict, List, Optional, Tuple, Set
from dataclasses import dataclass, asdict
import heapq


@dataclass
class CausalEdge:
    """Represents a causal relationship between two nodes."""
    id: str
    from_node: str
    to_node: str
    effect: str  # "positive", "negative", "neutral"
    weight: float  # [0, 1] - strength of relationship
    lag: str  # e.g., "0d", "1d", "4h"
    confidence: float  # [0, 1] - confidence in relationship
    condition: str  # conditional expression


@dataclass
class CausalPath:
    """Represents a path from source to target in causal graph."""
    source: str
    target: str
    path: List[str]  # node sequence
    confidence: float  # product of edge confidences
    effect_direction: str  # "positive" or "negative"
    total_lag: str  # aggregated lag
    edges: List[CausalEdge]


class CausalGraph:
    """Parse and analyze causal relationships."""

    def __init__(self, graph_path: str):
        """Initialize causal graph from JSON file."""
        self.graph_path = graph_path
        self.nodes: Dict[str, Dict] = {}
        self.edges: Dict[str, CausalEdge] = {}
        self.adjacency: Dict[str, List[str]] = {}  # from_node -> [to_nodes]
        self.reverse_adjacency: Dict[str, List[str]] = {}  # to_node -> [from_nodes]
        self._load_graph()

    def _load_graph(self) -> None:
        """Load and parse graph JSON."""
        try:
            with open(self.graph_path, 'r') as f:
                data = json.load(f)

            # Load nodes
            for node in data.get("nodes", []):
                node_id = node["id"]
                self.nodes[node_id] = node
                self.adjacency[node_id] = []
                self.reverse_adjacency[node_id] = []

            # Load edges
            for edge in data.get("edges", []):
                edge_obj = CausalEdge(
                    id=edge["id"],
                    from_node=edge["from"],
                    to_node=edge["to"],
                    effect=edge.get("effect", "neutral"),
                    weight=float(edge.get("weight", 0.5)),
                    lag=edge.get("lag", "0d"),
                    confidence=float(edge.get("confidence", 0.5)),
                    condition=edge.get("condition", "always")
                )
                self.edges[edge["id"]] = edge_obj

                # Build adjacency lists
                if edge["from"] in self.adjacency:
                    self.adjacency[edge["from"]].append(edge["to"])
                if edge["to"] in self.reverse_adjacency:
                    self.reverse_adjacency[edge["to"]].append(edge["from"])

        except Exception as e:
            raise RuntimeError(f"Failed to load causal graph: {str(e)}")

    def get_node(self, node_id: str) -> Optional[Dict]:
        """Get node information by ID."""
        return self.nodes.get(node_id)

    def get_edge(self, edge_id: str) -> Optional[CausalEdge]:
        """Get edge information by ID."""
        return self.edges.get(edge_id)

    def get_edges_from(self, source: str) -> List[CausalEdge]:
        """Get all edges originating from a node."""
        targets = self.adjacency.get(source, [])
        edges = []
        for target in targets:
            for edge_id, edge in self.edges.items():
                if edge.from_node == source and edge.to_node == target:
                    edges.append(edge)
        return edges

    def get_edges_to(self, target: str) -> List[CausalEdge]:
        """Get all edges pointing to a node."""
        sources = self.reverse_adjacency.get(target, [])
        edges = []
        for source in sources:
            for edge_id, edge in self.edges.items():
                if edge.from_node == source and edge.to_node == target:
                    edges.append(edge)
        return edges

    def find_shortest_path(
        self, source: str, target: str, use_confidence: bool = True
    ) -> Optional[CausalPath]:
        """
        Find shortest causal path from source to target using BFS.
        
        Args:
            source: Source node ID
            target: Target node ID
            use_confidence: If True, use confidence as edge weight (higher = better)
            
        Returns:
            CausalPath or None if no path exists
        """
        if source not in self.nodes or target not in self.nodes:
            return None

        visited: Set[str] = {source}
        queue: List[Tuple[str, List[str], List[CausalEdge]]] = [(source, [source], [])]

        while queue:
            current, path, edges_in_path = queue.pop(0)

            if current == target:
                # Calculate aggregate confidence
                confidence = 1.0
                for edge in edges_in_path:
                    confidence *= edge.confidence

                # Calculate effect direction
                effect = "neutral"
                neg_count = sum(1 for e in edges_in_path if e.effect == "negative")
                if neg_count % 2 == 1:
                    effect = "negative"
                elif any(e.effect == "positive" for e in edges_in_path):
                    effect = "positive"

                return CausalPath(
                    source=source,
                    target=target,
                    path=path,
                    confidence=confidence,
                    effect_direction=effect,
                    total_lag="0d",  # Simplified for now
                    edges=edges_in_path
                )

            for next_node in self.adjacency.get(current, []):
                if next_node not in visited:
                    visited.add(next_node)

                    # Find edge(s) from current to next_node
                    edge_list = []
                    for edge_id, edge in self.edges.items():
                        if edge.from_node == current and edge.to_node == next_node:
                            edge_list.append(edge)

                    for edge in edge_list:
                        queue.append(
                            (next_node, path + [next_node], edges_in_path + [edge])
                        )

        return None

    def find_all_paths(
        self, source: str, target: str, max_depth: int = 5
    ) -> List[CausalPath]:
        """
        Find all causal paths up to max_depth.
        
        Uses DFS to explore all possible paths.
        """
        if source not in self.nodes or target not in self.nodes:
            return []

        paths: List[CausalPath] = []

        def dfs(current: str, visited: Set[str], path: List[str], edges_in_path: List[CausalEdge], depth: int):
            if depth > max_depth:
                return

            if current == target:
                confidence = 1.0
                for edge in edges_in_path:
                    confidence *= edge.confidence

                neg_count = sum(1 for e in edges_in_path if e.effect == "negative")
                effect = "negative" if neg_count % 2 == 1 else "positive"

                paths.append(CausalPath(
                    source=source,
                    target=target,
                    path=path,
                    confidence=confidence,
                    effect_direction=effect,
                    total_lag="0d",
                    edges=edges_in_path
                ))
                return

            for next_node in self.adjacency.get(current, []):
                if next_node not in visited:
                    visited.add(next_node)

                    for edge_id, edge in self.edges.items():
                        if edge.from_node == current and edge.to_node == next_node:
                            dfs(next_node, visited.copy(), path + [next_node], edges_in_path + [edge], depth + 1)

        dfs(source, {source}, [source], [], 0)
        
        # Sort by confidence descending
        paths.sort(key=lambda p: p.confidence, reverse=True)
        return paths

    def get_influencers(self, target: str, max_depth: int = 3) -> List[Tuple[str, float]]:
        """
        Find all nodes that can influence a target, ranked by aggregated confidence.
        
        Returns list of (node_id, aggregated_confidence) tuples.
        """
        if target not in self.nodes:
            return []

        influencers: Dict[str, float] = {}

        def dfs(current: str, visited: Set[str], confidence: float, depth: int):
            if depth > max_depth:
                return

            if current != target and current in influencers:
                influencers[current] = max(influencers[current], confidence)
            elif current != target:
                influencers[current] = confidence

            for source in self.reverse_adjacency.get(current, []):
                if source not in visited:
                    visited.add(source)

                    # Find edge confidence
                    for edge_id, edge in self.edges.items():
                        if edge.from_node == source and edge.to_node == current:
                            new_confidence = confidence * edge.confidence
                            dfs(source, visited.copy(), new_confidence, depth + 1)

        dfs(target, {target}, 1.0, 0)

        result = sorted(influencers.items(), key=lambda x: x[1], reverse=True)
        return result

    def get_descendants(self, source: str, max_depth: int = 3) -> List[Tuple[str, float]]:
        """
        Find all nodes influenced by a source, ranked by aggregated confidence.
        
        Returns list of (node_id, aggregated_confidence) tuples.
        """
        if source not in self.nodes:
            return []

        descendants: Dict[str, float] = {}

        def dfs(current: str, visited: Set[str], confidence: float, depth: int):
            if depth > max_depth:
                return

            if current != source and current in descendants:
                descendants[current] = max(descendants[current], confidence)
            elif current != source:
                descendants[current] = confidence

            for target in self.adjacency.get(current, []):
                if target not in visited:
                    visited.add(target)

                    # Find edge confidence
                    for edge_id, edge in self.edges.items():
                        if edge.from_node == current and edge.to_node == target:
                            new_confidence = confidence * edge.confidence
                            dfs(target, visited.copy(), new_confidence, depth + 1)

        dfs(source, {source}, 1.0, 0)

        result = sorted(descendants.items(), key=lambda x: x[1], reverse=True)
        return result

    def get_summary(self) -> Dict:
        """Get summary statistics of the graph."""
        return {
            "num_nodes": len(self.nodes),
            "num_edges": len(self.edges),
            "node_types": list(set(n.get("type") for n in self.nodes.values())),
            "version": "1.0.0",  # TODO: Load from graph
        }


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python causal_graph.py <path_to_causal_graph.json>")
        sys.exit(1)

    graph_path = sys.argv[1]
    graph = CausalGraph(graph_path)

    print("\nCausal Graph Summary:")
    print(json.dumps(graph.get_summary(), indent=2))

    print("\nExample: Paths from DXY to BTC:")
    paths = graph.find_all_paths("DXY", "BTC", max_depth=3)
    for path in paths[:3]:
        print(f"  {' -> '.join(path.path)} (confidence: {path.confidence:.2f}, effect: {path.effect_direction})")
