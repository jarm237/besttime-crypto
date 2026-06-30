"""
Causal System Initialization - Bot Startup Integration

Called during bot initialization to set up all causal components.
MUST succeed before bot proceeds, otherwise bot refuses to start.
"""

import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class CausalSystemInitializer:
    """Initializes all causal system components at bot startup."""

    def __init__(self):
        """Initialize causal system components."""
        self.graph = None
        self.context_engine = None
        self.reasoning_engine = None
        self.scenario_simulator = None
        self.initialized = False

    def initialize(self, config: Optional[Dict] = None) -> bool:
        """
        Initialize causal system. Raises exception if any step fails.
        
        Args:
            config: Optional configuration dict with paths to:
                - graph_path: Path to causal_graph.json
                - rules_path: Path to context_rules.json
                
        Returns:
            True if initialization successful, False otherwise
        """
        config = config or {}
        graph_path = config.get("graph_path", "data/causal_graph.json")
        rules_path = config.get("rules_path", "data/context_rules.json")

        try:
            logger.info("="*80)
            logger.info("INITIALIZING CAUSAL SYSTEM")
            logger.info("="*80)

            # Step 1: Validate graph (CRITICAL)
            logger.info("\n[1/4] Validating causal graph...")
            if not self._validate_graph(graph_path):
                raise RuntimeError("Graph validation failed")
            logger.info("✓ Graph validation passed")

            # Step 2: Load causal graph
            logger.info("\n[2/4] Loading causal graph...")
            if not self._load_graph(graph_path):
                raise RuntimeError("Graph loading failed")
            logger.info(f"✓ Graph loaded: {self.graph.get_summary()}")

            # Step 3: Initialize context engine
            logger.info("\n[3/4] Initializing context engine...")
            if not self._load_context_engine(rules_path):
                raise RuntimeError("Context engine initialization failed")
            logger.info(f"✓ Context engine initialized with rules")

            # Step 4: Initialize reasoning engine
            logger.info("\n[4/4] Initializing causal reasoning engine...")
            if not self._load_reasoning_engine():
                raise RuntimeError("Reasoning engine initialization failed")
            logger.info(f"✓ Reasoning engine initialized")

            self.initialized = True
            logger.info("\n" + "="*80)
            logger.info("✓ CAUSAL SYSTEM INITIALIZATION SUCCESSFUL")
            logger.info("="*80 + "\n")

            return True

        except Exception as e:
            logger.error(f"\n✗ CAUSAL SYSTEM INITIALIZATION FAILED: {str(e)}")
            logger.error("Bot cannot proceed without valid causal system")
            logger.error("="*80 + "\n")
            raise

    def _validate_graph(self, graph_path: str) -> bool:
        """Validate causal graph structure."""
        try:
            from .graph_validator import validate_graph_or_fail
            validate_graph_or_fail(graph_path)
            return True
        except Exception as e:
            logger.error(f"Graph validation error: {str(e)}")
            return False

    def _load_graph(self, graph_path: str) -> bool:
        """Load causal graph."""
        try:
            from .causal_graph import CausalGraph
            self.graph = CausalGraph(graph_path)
            return True
        except Exception as e:
            logger.error(f"Graph loading error: {str(e)}")
            return False

    def _load_context_engine(self, rules_path: str) -> bool:
        """Initialize context engine."""
        try:
            from .context_engine import ContextEngine
            self.context_engine = ContextEngine(rules_path)
            return True
        except Exception as e:
            logger.error(f"Context engine initialization error: {str(e)}")
            return False

    def _load_reasoning_engine(self) -> bool:
        """Initialize reasoning engine."""
        try:
            from .causal_reasoning import CausalReasoningEngine
            self.reasoning_engine = CausalReasoningEngine("data/causal_graph.json")
            return True
        except Exception as e:
            logger.error(f"Reasoning engine initialization error: {str(e)}")
            return False

    def get_components(self) -> Dict:
        """Return initialized components."""
        if not self.initialized:
            raise RuntimeError("Causal system not initialized")

        return {
            "graph": self.graph,
            "context_engine": self.context_engine,
            "reasoning_engine": self.reasoning_engine,
        }


def initialize_causal_system_at_startup(config: Optional[Dict] = None) -> Dict:
    """
    Main entry point for bot startup.
    
    Call this function in main.py or your bot initialization code:
    
    ```python
    # In main.py or startup code
    from btc_scraper.ml_engine.causal_startup import initialize_causal_system_at_startup
    
    try:
        causal_system = initialize_causal_system_at_startup()
        # Bot can proceed
    except Exception as e:
        # Bot refuses to start
        logger.critical(f"Cannot start without causal system: {str(e)}")
        sys.exit(1)
    ```
    """
    initializer = CausalSystemInitializer()
    initializer.initialize(config)
    return initializer.get_components()


if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    try:
        components = initialize_causal_system_at_startup()
        print("\n✓ Causal system ready")
        print(f"  - Graph: {components['graph'].get_summary()}")
        sys.exit(0)
    except Exception as e:
        print(f"\n✗ Failed to initialize: {str(e)}")
        sys.exit(1)
