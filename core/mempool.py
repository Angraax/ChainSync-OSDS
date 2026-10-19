"""
ChainSync Mempool & TICK Generator (Task T3)
Manages pending transactions before consensus block packaging.
Features:
- Ingress signature validation
- Deduplication by (sender, request_id)
- FIFO batching for block proposal
- Automatic TICK generation to guarantee lease progression even when idle
"""

import time
from typing import Dict, List, Tuple, Optional, Set
from core.models import Transaction, TransactionType


class Mempool:
    def __init__(self, max_capacity: int = 1000):
        self.max_capacity = max_capacity
        self.pending: List[Transaction] = []
        # Fast lookup set: (sender, request_id)
        self.seen_keys: Set[Tuple[str, str]] = set()

    def add_transaction(self, tx: Transaction) -> Tuple[bool, str]:
        """
        Validates signature and deduplicates before adding to mempool.
        """
        if len(self.pending) >= self.max_capacity:
            return False, "Mempool is full"

        # Validate cryptographic signature (except TICK)
        if tx.type != TransactionType.TICK:
            if not tx.verify():
                return False, "Invalid transaction signature"

        # Deduplication
        if tx.request_id:
            key = (tx.sender, tx.request_id)
            if key in self.seen_keys:
                return False, "Duplicate transaction already in mempool"
            self.seen_keys.add(key)

        self.pending.append(tx)
        return True, "Accepted"

    def drain_batch(self, max_batch_size: int = 50, include_tick: bool = True) -> List[Transaction]:
        """
        Extracts up to max_batch_size transactions to form a new block.
        Always prepends a TICK transaction if include_tick is True.
        """
        batch: List[Transaction] = []

        if include_tick:
            # TICK transaction allows state machine to advance block time deterministically
            batch.append(Transaction(type=TransactionType.TICK, request_id="tick"))

        count = 0
        while self.pending and count < max_batch_size:
            tx = self.pending.pop(0)
            batch.append(tx)
            count += 1

        return batch

    def clear(self):
        self.pending.clear()
        self.seen_keys.clear()

    def size(self) -> int:
        return len(self.pending)
