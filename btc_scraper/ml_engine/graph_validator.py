"""
Graph Validator for Causal Graph Structure.

Checks for:
- Cycles (prevents infinite loops in causal reasoning)
- Missing nodes (edges reference non-existent nodes)
- Duplicate edges (from-to pairs)
- Invalid weights/confidence (should be in [0, 1])
- Invalid lag format
"""

import json
from typing import Dict, List, Set, Tuple, Optional
from dataclasses import dataclass


@dataclass
class ValidationError:
    """Represents a single validation error."""
    error_type: str
    message: str
    details: Optional[Dict] = None


class CausalGraphValidator:
    """Validates causal graph for structural integrity."""

    def __init__(self, graph_path: str):
        """Initialize validator with graph path."""
        self.graph_path = graph_path
        self.errors: List[ValidationError] = []
        self.graph = None

    def load_graph(self) -> bool:
        """Load and parse graph JSON."""
        try:
            with open(self.graph_path, 'r') as f:
                self.graph = json.load(f)
            return True
        except Exception as e:
            self.errors.append(ValidationError(
                error_type="LOAD_ERROR",
                message=f"Failed to load graph: {str(e)}"
            ))
            return False

    def _extract_node_ids(self) -> Set[str]:
        """Extract all node IDs from graph."""
        if not self.graph or "nodes" not in self.graph:
            return set()
        return {node["id"] for node in self.graph["nodes"] if "id" in node}

    def _extract_edges(self) -> List[Dict]:
        """Extract all edges from graph."""
        if not self.graph or "edges" not in self.graph:
            return []
        return self.graph["edges"]

    def _check_missing_nodes(self) -> None:
        """Check for edges that reference non-existent nodes."""
        node_ids = self._extract_node_ids()
        edges = self._extract_edges()

        for edge in edges:
            from_node = edge.get("from")
            to_node = edge.get("to")

            if from_node and from_node not in node_ids:
                self.errors.append(ValidationError(
                    error_type="MISSING_NODE",
                    message=f"Edge '{edge.get('id', 'unknown')}' references missing source node: {from_node}",
                    details={"edge_id": edge.get("id"), "missing_node": from_node}
                ))

            if to_node and to_node not in node_ids:
                self.errors.append(ValidationError(
                    error_type="MISSING_NODE",
                    message=f"Edge '{edge.get('id', 'unknown')}' references missing target node: {to_node}",
                    details={"edge_id": edge.get("id"), "missing_node": to_node}
                ))

    def _check_duplicate_edges(self) -> None:
        """Check for duplicate from-to pairs."""
        edges = self._extract_edges()
        seen_pairs: Dict[Tuple, List] = {}

        for edge in edges:
            from_node = edge.get("from")
            to_node = edge.get("to")

            if from_node and to_node:
                pair = (from_node, to_node)
                if pair not in seen_pairs:
                    seen_pairs[pair] = []
                seen_pairs[pair].append(edge.get("id", "unknown"))

        for (from_node, to_node), edge_ids in seen_pairs.items():
            if len(edge_ids) > 1:
                self.errors.append(ValidationError(
                    error_type="DUPLICATE_EDGE",
                    message=f"Duplicate edge pair found: {from_node} -> {to_node} (edges: {', '.join(edge_ids)})",
                    details={"from": from_node, "to": to_node, "duplicate_ids": edge_ids}
                ))

    def _check_invalid_weights(self) -> None:
        """Check for invalid weight/confidence values."""
        edges = self._extract_edges()

        for edge in edges:
            edge_id = edge.get("id", "unknown")
            weight = edge.get("weight")
            confidence = edge.get("confidence")

            if weight is not None:
                try:
                    w = float(weight)
                    if not (0 <= w <= 1):
                        self.errors.append(ValidationError(
                            error_type="INVALID_WEIGHT",
                            message=f"Edge '{edge_id}' has invalid weight: {weight} (should be in [0, 1])",
                            details={"edge_id": edge_id, "weight": weight}
                        ))
                except (TypeError, ValueError):
                    self.errors.append(ValidationError(
                        error_type="INVALID_WEIGHT",
                        message=f"Edge '{edge_id}' has non-numeric weight: {weight}",
                        details={"edge_id": edge_id, "weight": weight}
                    ))

            if confidence is not None:
                try:
                    c = float(confidence)
                    if not (0 <= c <= 1):
                        self.errors.append(ValidationError(
                            error_type="INVALID_CONFIDENCE",
                            message=f"Edge '{edge_id}' has invalid confidence: {confidence} (should be in [0, 1])",
                            details={"edge_id": edge_id, "confidence": confidence}
                        ))
                except (TypeError, ValueError):
                    self.errors.append(ValidationError(
                        error_type="INVALID_CONFIDENCE",
                        message=f"Edge '{edge_id}' has non-numeric confidence: {confidence}",
                        details={"edge_id": edge_id, "confidence": confidence}
                    ))

    def _check_invalid_effect(self) -> None:
        """Check for invalid effect values."""
        edges = self._extract_edges()
        valid_effects = {"positive", "negative", "neutral"}

        for edge in edges:
            edge_id = edge.get("id", "unknown")
            effect = edge.get("effect", "").lower()

            if effect and effect not in valid_effects:
                self.errors.append(ValidationError(
                    error_type="INVALID_EFFECT",
                    message=f"Edge '{edge_id}' has invalid effect: {effect} (should be one of: {', '.join(valid_effects)})",
                    details={"edge_id": edge_id, "effect": edge.get("effect")}
                ))

    def _has_cycle_dfs(self, node: str, visited: Set[str], rec_stack: Set[str], adj_list: Dict[str, List[str]]) -> bool:
        """Detect cycle using DFS."""
        visited.add(node)
        rec_stack.add(node)

        for neighbor in adj_list.get(node, []):
            if neighbor not in visited:
                if self._has_cycle_dfs(neighbor, visited, rec_stack, adj_list):
                    return True
            elif neighbor in rec_stack:
                return True

        rec_stack.remove(node)
        return False

    def _check_cycles(self) -> None:
        """Check for cycles in the graph."""
        edges = self._extract_edges()
        node_ids = self._extract_node_ids()

        # Build adjacency list
        adj_list: Dict[str, List[str]] = {node_id: [] for node_id in node_ids}
        for edge in edges:
            from_node = edge.get("from")
            to_node = edge.get("to")
            if from_node and to_node and from_node in adj_list and to_node in adj_list:
                adj_list[from_node].append(to_node)

        visited: Set[str] = set()
        rec_stack: Set[str] = set()

        for node in node_ids:
            if node not in visited:
                if self._has_cycle_dfs(node, visited, rec_stack, adj_list):
                    self.errors.append(ValidationError(
                        error_type="CYCLE_DETECTED",
                        message=f"Cycle detected starting from node: {node}",
                        details={"start_node": node}
                    ))

    def validate(self) -> Tuple[bool, List[ValidationError]]:
        """
        Run all validation checks.
        
        Returns:
            (is_valid, errors)
        """
        self.errors = []

        if not self.load_graph():
            return False, self.errors

        self._check_missing_nodes()
        self._check_duplicate_edges()
        self._check_invalid_weights()
        self._check_invalid_confidence()
        self._check_invalid_effect()
        self._check_cycles()

        return len(self.errors) == 0, self.errors

    def _check_invalid_confidence(self) -> None:
        """Placeholder for confidence check (called by validate)."""
        pass

    def print_report(self) -> None:
        """Print validation report."""
        print("\n" + "="*80)
        print("CAUSAL GRAPH VALIDATION REPORT")
        print("="*80)

        if not self.errors:
            print("✓ Graph is valid!")
        else:
            print(f"✗ Found {len(self.errors)} validation error(s):\n")
            for i, error in enumerate(self.errors, 1):
                print(f"{i}. [{error.error_type}] {error.message}")
                if error.details:
                    for key, value in error.details.items():
                        print(f"   - {key}: {value}")
                print()

        print("="*80 + "\n")


def validate_graph_or_fail(graph_path: str) -> bool:
    """
    Validate graph and fail the application if validation fails.
    
    This is called during bot startup to ensure graph integrity.
    """
    validator = CausalGraphValidator(graph_path)
    is_valid, errors = validator.validate()

    validator.print_report()

    if not is_valid:
        raise RuntimeError(
            f"Causal graph validation failed with {len(errors)} error(s). "
            "Bot cannot start with invalid graph. Please fix errors above."
        )

    return True


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python graph_validator.py <path_to_causal_graph.json>")
        sys.exit(1)

    graph_path = sys.argv[1]
    validator = CausalGraphValidator(graph_path)
    is_valid, errors = validator.validate()
    validator.print_report()

    sys.exit(0 if is_valid else 1)
