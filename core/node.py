"""
ChainSync Node Engine
Integrates LockManager (T1), Ledger (T2), and Mempool (T3) into a single unified node.
Provides the exact contract needed for Ujjwal's consensus/gateway layer.
"""

import time
from typing import List, Dict, Optional, Tuple, Callable, Any
from core.models import Transaction, Block, Event, SemaphoreSnapshot
from core.lock_manager import LockManager
from core.ledger import Ledger
from core.mempool import Mempool


class ChainSyncNode:
    def __init__(self, node_id: str = "node-1", storage_path: str = "data/ledger.jsonl"):
        self.node_id = node_id
        self.lock_manager = LockManager()
        self.ledger = Ledger(storage_path=storage_path)
        self.mempool = Mempool()
        self.event_subscribers: List[Callable[[Event], None]] = []

        # Replay ledger from disk to restore state
        self.ledger.replay(self.lock_manager)

    def subscribe_events(self, callback: Callable[[Event], None]):
        """Registers a listener for real-time state machine events."""
        self.event_subscribers.append(callback)

    def _broadcast_event(self, event: Event):
        for sub in self.event_subscribers:
            try:
                sub(event)
            except Exception:
                pass

    def submit_tx(self, tx: Transaction) -> Tuple[bool, str]:
        """Ingress point for transactions from client SDK or gateway."""
        return self.mempool.add_transaction(tx)

    def produce_block(self, block_time_ms: Optional[int] = None, max_tx: int = 50) -> Optional[Block]:
        """
        Consensus block packaging. Drains pending mempool transactions,
        packages candidate block, commits it to ledger, and applies it to LockManager.
        """
        btime = block_time_ms if block_time_ms is not None else int(time.time() * 1000)
        # Ensure monotonic timestamp
        last_time = self.ledger.latest_block.header.timestamp
        if btime <= last_time:
            btime = last_time + 1000

        batch = self.mempool.drain_batch(max_batch_size=max_tx, include_tick=True)
        new_height = self.ledger.height + 1

        block = Block.create(
            height=new_height,
            prev_hash=self.ledger.latest_block.block_hash,
            timestamp=btime,
            proposer=self.node_id,
            transactions=batch
        )

        # 1. Append to cryptographic ledger
        success, err = self.ledger.append_block(block)
        if not success:
            raise RuntimeError(f"Failed to append block to ledger: {err}")

        # 2. Execute transactions against LockManager state machine
        for tx in block.transactions:
            result, events = self.lock_manager.apply(tx, block_time=btime, block_height=new_height)
            for ev in events:
                self._broadcast_event(ev)

        return block

    def get_semaphore(self, name: str) -> Optional[SemaphoreSnapshot]:
        return self.lock_manager.get_state(name)

    def get_all_semaphores(self) -> Dict[str, SemaphoreSnapshot]:
        return self.lock_manager.get_all_states()

    def get_blocks(self) -> List[Block]:
        return self.ledger.blocks
