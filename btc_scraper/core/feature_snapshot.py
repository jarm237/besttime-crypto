"""
Feature Snapshot & Replay - Store and restore complete market state.

Enables:
1. Replay: Re-run analysis on historical state
2. Backtest: Test with exact feature values from past
3. Debug: Replay decision when issue occurs
4. Counterfactual: Test "what if" scenarios with modified state

Key principle: Never run analysis on live data, always take snapshot first.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Any, Optional, List
import json
import os
from pathlib import Path
import hashlib

from btc_scraper.core.world_state import WorldState
from btc_scraper.core.event_bus import Event


@dataclass
class FeatureSnapshot:
    """
    Complete state snapshot at a point in time.
    
    Includes:
    - World state (macro, liquidity, crypto, sentiment, risk)
    - Context report (if generated)
    - Events that triggered this snapshot
    - Metadata for replay
    """
    snapshot_id: str
    timestamp: datetime
    world_state: Dict[str, Any]  # Serialized WorldState
    context_report: Optional[Dict[str, Any]] = None
    events: List[Dict[str, Any]] = None  # Serialized events
    reasoning_data: Optional[Dict[str, Any]] = None
    decision: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.events is None:
            self.events = []
        if self.metadata is None:
            self.metadata = {}
    
    def hash(self) -> str:
        """Generate hash of snapshot for integrity check."""
        data = f"{self.snapshot_id}{self.timestamp}{json.dumps(self.world_state)}"
        return hashlib.sha256(data.encode()).hexdigest()[:16]
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "snapshot_id": self.snapshot_id,
            "timestamp": self.timestamp.isoformat(),
            "world_state": self.world_state,
            "context_report": self.context_report,
            "events": self.events,
            "reasoning_data": self.reasoning_data,
            "decision": self.decision,
            "metadata": self.metadata,
            "hash": self.hash(),
        }
    
    @staticmethod
    def from_dict(data: Dict[str, Any]) -> 'FeatureSnapshot':
        """Deserialize from dictionary."""
        return FeatureSnapshot(
            snapshot_id=data["snapshot_id"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            world_state=data["world_state"],
            context_report=data.get("context_report"),
            events=data.get("events", []),
            reasoning_data=data.get("reasoning_data"),
            decision=data.get("decision"),
            metadata=data.get("metadata", {}),
        )
    
    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), indent=2)
    
    @staticmethod
    def from_json(json_str: str) -> 'FeatureSnapshot':
        """Deserialize from JSON string."""
        data = json.loads(json_str)
        return FeatureSnapshot.from_dict(data)


class SnapshotManager:
    """
    Manage feature snapshots (create, store, retrieve).
    
    Snapshots are stored in:
    - Memory (recent, for quick replay)
    - Disk (persistent, for long-term backtest)
    """
    
    def __init__(self, snapshot_dir: str = "data/snapshots"):
        """
        Args:
            snapshot_dir: Directory to store snapshot files
        """
        self.snapshot_dir = Path(snapshot_dir)
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        
        # In-memory cache (keep last N)
        self.max_memory_snapshots = 1000
        self._memory_snapshots: Dict[str, FeatureSnapshot] = {}
    
    def create_snapshot(self, world_state: WorldState, 
                       snapshot_id: Optional[str] = None,
                       context_report: Optional[Dict[str, Any]] = None,
                       events: Optional[List[Event]] = None,
                       decision: Optional[Dict[str, Any]] = None,
                       metadata: Optional[Dict[str, Any]] = None) -> FeatureSnapshot:
        """
        Create a feature snapshot.
        
        Args:
            world_state: Current world state
            snapshot_id: Unique ID (auto-generated if not provided)
            context_report: Context report if generated
            events: Events that triggered this snapshot
            decision: Decision made after analysis
            metadata: Additional metadata
        
        Returns:
            Created snapshot
        """
        if snapshot_id is None:
            snapshot_id = f"snap_{world_state.timestamp.timestamp()}_{len(self._memory_snapshots)}"
        
        serialized_events = []
        if events:
            serialized_events = [e.to_dict() for e in events]
        
        snapshot = FeatureSnapshot(
            snapshot_id=snapshot_id,
            timestamp=world_state.timestamp,
            world_state=world_state.to_dict(),
            context_report=context_report,
            events=serialized_events,
            decision=decision,
            metadata=metadata or {},
        )
        
        # Store in memory
        self._memory_snapshots[snapshot_id] = snapshot
        
        # Prune old snapshots from memory if needed
        if len(self._memory_snapshots) > self.max_memory_snapshots:
            oldest_id = min(
                self._memory_snapshots.keys(),
                key=lambda sid: self._memory_snapshots[sid].timestamp
            )
            del self._memory_snapshots[oldest_id]
        
        return snapshot
    
    def save_snapshot(self, snapshot: FeatureSnapshot, 
                     filename: Optional[str] = None) -> str:
        """
        Save snapshot to disk.
        
        Args:
            snapshot: Snapshot to save
            filename: Filename (auto-generated if not provided)
        
        Returns:
            Full path to saved file
        """
        if filename is None:
            filename = f"{snapshot.snapshot_id}.json"
        
        filepath = self.snapshot_dir / filename
        
        with open(filepath, 'w') as f:
            f.write(snapshot.to_json())
        
        return str(filepath)
    
    def load_snapshot(self, snapshot_id: str) -> Optional[FeatureSnapshot]:
        """
        Load snapshot (from memory first, then disk).
        
        Args:
            snapshot_id: Snapshot ID to load
        
        Returns:
            Snapshot or None if not found
        """
        # Check memory first
        if snapshot_id in self._memory_snapshots:
            return self._memory_snapshots[snapshot_id]
        
        # Try disk
        filepath = self.snapshot_dir / f"{snapshot_id}.json"
        if filepath.exists():
            with open(filepath, 'r') as f:
                return FeatureSnapshot.from_json(f.read())
        
        return None
    
    def load_snapshot_from_file(self, filepath: str) -> Optional[FeatureSnapshot]:
        """Load snapshot from specific file."""
        try:
            with open(filepath, 'r') as f:
                return FeatureSnapshot.from_json(f.read())
        except Exception as e:
            print(f"Error loading snapshot from {filepath}: {str(e)}")
            return None
    
    def list_snapshots(self) -> List[str]:
        """List all snapshot IDs (memory + disk)."""
        memory_ids = list(self._memory_snapshots.keys())
        
        disk_ids = []
        if self.snapshot_dir.exists():
            for filepath in self.snapshot_dir.glob("*.json"):
                snap_id = filepath.stem
                if snap_id not in memory_ids:
                    disk_ids.append(snap_id)
        
        return memory_ids + disk_ids
    
    def delete_old_snapshots(self, days: int = 7) -> int:
        """
        Delete snapshots older than N days.
        
        Args:
            days: Delete if older than this many days
        
        Returns:
            Number of snapshots deleted
        """
        from datetime import timedelta
        
        cutoff = datetime.now() - timedelta(days=days)
        deleted_count = 0
        
        # Delete from memory
        to_delete = [
            sid for sid, snap in self._memory_snapshots.items()
            if snap.timestamp < cutoff
        ]
        for sid in to_delete:
            del self._memory_snapshots[sid]
            deleted_count += 1
        
        # Delete from disk
        if self.snapshot_dir.exists():
            for filepath in self.snapshot_dir.glob("*.json"):
                try:
                    with open(filepath, 'r') as f:
                        snap = FeatureSnapshot.from_json(f.read())
                        if snap.timestamp < cutoff:
                            filepath.unlink()
                            deleted_count += 1
                except Exception:
                    pass
        
        return deleted_count
    
    def get_stats(self) -> Dict[str, Any]:
        """Get snapshot statistics."""
        memory_count = len(self._memory_snapshots)
        
        disk_count = 0
        total_disk_size = 0
        if self.snapshot_dir.exists():
            for filepath in self.snapshot_dir.glob("*.json"):
                disk_count += 1
                total_disk_size += filepath.stat().st_size
        
        return {
            "memory_snapshots": memory_count,
            "disk_snapshots": disk_count,
            "total_snapshots": memory_count + disk_count,
            "disk_size_bytes": total_disk_size,
            "snapshot_dir": str(self.snapshot_dir),
        }


class SnapshotReplayer:
    """
    Replay analysis using stored snapshots.
    
    Useful for:
    - Debugging: "Why did we make that decision?"
    - Backtesting: "What would happen with those exact conditions?"
    - Counterfactual: "What if we changed X?"
    """
    
    def __init__(self, snapshot_manager: SnapshotManager):
        self.manager = snapshot_manager
    
    def replay_decision(self, snapshot: FeatureSnapshot) -> Dict[str, Any]:
        """
        Replay the decision from a snapshot.
        
        In practice, this would:
        1. Load world state from snapshot
        2. Run through Context Engine
        3. Run through Reasoning Engine
        4. Run through Decision Engine
        5. Compare with original decision
        
        Args:
            snapshot: Snapshot to replay
        
        Returns:
            Replay results with comparison to original
        """
        world_state_dict = snapshot.world_state
        
        # In real implementation:
        # world_state = WorldState.from_dict(world_state_dict)
        # context_report = context_engine.generate_context_report(...)
        # etc.
        
        return {
            "snapshot_id": snapshot.snapshot_id,
            "original_decision": snapshot.decision,
            "replayed_decision": "TODO: implement actual replay",
            "decision_matches": None,  # Will be set in implementation
        }
    
    def counterfactual_analysis(self, snapshot: FeatureSnapshot,
                               modifications: Dict[str, Any]) -> Dict[str, Any]:
        """
        Run counterfactual analysis: "What if X was different?"
        
        Example modifications:
        {
            "macro.DXY": 102.0,  # Instead of 104.5
            "sentiment.FearGreed": 20,  # Instead of 65
        }
        
        Args:
            snapshot: Base snapshot
            modifications: Dict of path → new_value
        
        Returns:
            Results of counterfactual decision
        """
        # In real implementation:
        # 1. Load world state from snapshot
        # 2. Apply modifications
        # 3. Run through decision pipeline
        # 4. Compare original vs counterfactual
        
        return {
            "snapshot_id": snapshot.snapshot_id,
            "modifications": modifications,
            "original_decision": snapshot.decision,
            "counterfactual_decision": "TODO: implement actual counterfactual",
        }


if __name__ == "__main__":
    # Test
    from btc_scraper.core.world_state import WorldState
    
    manager = SnapshotManager()
    
    # Create snapshot
    world_state = WorldState(timestamp=datetime.now())
    world_state.macro.DXY = 104.5
    world_state.crypto.BTC_Price = 52000
    
    snapshot = manager.create_snapshot(
        world_state=world_state,
        decision={"action": "BUY", "posterior": 0.75},
        metadata={"test": True}
    )
    
    # Save and load
    filepath = manager.save_snapshot(snapshot)
    loaded = manager.load_snapshot(snapshot.snapshot_id)
    
    print(f"✓ Snapshot Manager test complete")
    print(f"  Snapshot ID: {snapshot.snapshot_id}")
    print(f"  Hash: {snapshot.hash()}")
    print(f"  Saved to: {filepath}")
    print(f"  Loaded OK: {loaded is not None}")
    print(f"  Stats: {manager.get_stats()}")
