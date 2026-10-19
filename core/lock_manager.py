"""
ChainSync Lock Manager (Task T1)
Deterministic State Machine implementing replicated semaphore synchronization rules.
Follows Chapter 17 & Section 3 specification:
- Pure deterministic logic: apply(tx, block_time) -> (result, events)
- No network, no random, no system clock
- Block-time lease expiry & queue promotion
- Strict FIFO queue ordering
- Strictly monotonic fencing tokens
- Idempotency deduplication via seen set
"""

from typing import Dict, List, Tuple, Any, Optional
from core.models import (
    Transaction,
    TransactionType,
    Event,
    EventType,
    HolderInfo,
    WaitRequest,
    SemaphoreSnapshot
)


class Semaphore:
    """Internal deterministic state of a single semaphore."""
    def __init__(self, name: str, capacity: int):
        self.name: str = name
        self.capacity: int = max(1, capacity)
        self.holders: Dict[int, HolderInfo] = {}  # token -> HolderInfo
        self.queue: List[WaitRequest] = []        # FIFO queue
        self.next_token: int = 1                  # Strictly monotonic counter

    def to_snapshot(self) -> SemaphoreSnapshot:
        return SemaphoreSnapshot(
            name=self.name,
            capacity=self.capacity,
            holders={str(k): v for k, v in self.holders.items()},
            queue=list(self.queue),
            next_token=self.next_token
        )


class LockManager:
    """
    Core Deterministic State Machine for ChainSync.
    Every node executes identical transactions in identical order at identical block_time,
    guaranteeing bit-for-bit identical state across all honest nodes.
    """
    def __init__(self):
        self.sems: Dict[str, Semaphore] = {}
        # Idempotency cache: (sender, request_id) -> cached_result
        self.seen: Dict[Tuple[str, str], Any] = {}
        self.last_block_time: int = 0
        self.block_height: int = 0

    def apply(self, tx: Transaction, block_time: int, block_height: int = 0) -> Tuple[Any, List[Event]]:
        """
        Pure deterministic state transition function.
        Receives committed transaction and agreed block timestamp.
        Returns: (execution_result, list_of_emitted_events)
        """
        events: List[Event] = []
        self.last_block_time = block_time
        self.block_height = block_height

        # 1. Deterministic housekeeping: expire old leases across all semaphores
        for sem in self.sems.values():
            events.extend(self._expire_leases(sem, block_time))

        # 2. TICK handling: Leader advances the consensus clock
        if tx.type == TransactionType.TICK:
            return "OK", events

        # 3. Idempotency check: Client retries return original result with no double effects
        if tx.request_id:
            cache_key = (tx.sender, tx.request_id)
            if cache_key in self.seen:
                # Return cached result and no duplicate events
                return self.seen[cache_key], []

        # 4. Transaction execution dispatch
        result = None
        if tx.type == TransactionType.CREATE:
            result, tx_events = self._create(tx, block_time)
        elif tx.type == TransactionType.ACQUIRE:
            result, tx_events = self._acquire(tx, block_time)
        elif tx.type == TransactionType.RELEASE:
            result, tx_events = self._release(tx, block_time)
        elif tx.type == TransactionType.RENEW:
            result, tx_events = self._renew(tx, block_time)
        else:
            result = "REJECTED_UNKNOWN_TYPE"
            tx_events = [Event(
                event=EventType.REJECTED,
                semaphore=tx.semaphore,
                holder=tx.sender,
                block_height=self.block_height,
                timestamp=block_time,
                details={"reason": "Unknown transaction type"}
            )]

        events.extend(tx_events)

        # Cache idempotent result
        if tx.request_id:
            self.seen[(tx.sender, tx.request_id)] = result

        return result, events

    def _expire_leases(self, sem: Semaphore, block_time: int) -> List[Event]:
        """Removes expired holders and promotes waiters from the queue."""
        events: List[Event] = []
        expired_tokens = [
            t for t, h in sem.holders.items() if h.expires_at <= block_time
        ]

        for token in expired_tokens:
            holder = sem.holders.pop(token)
            events.append(Event(
                event=EventType.EXPIRED,
                semaphore=sem.name,
                holder=holder.owner,
                token=token,
                expires_at=holder.expires_at,
                block_height=self.block_height,
                timestamp=block_time,
                details={"reason": "Lease expired at block time", "request_id": holder.request_id}
            ))

        # After freeing capacity, promote waiters
        events.extend(self._promote_waiters(sem, block_time))
        return events

    def _promote_waiters(self, sem: Semaphore, block_time: int) -> List[Event]:
        """Promotes queue head while capacity is available."""
        events: List[Event] = []
        while sem.queue and len(sem.holders) < sem.capacity:
            req = sem.queue.pop(0)
            token = sem.next_token
            sem.next_token += 1
            expires_at = block_time + req.lease_ms
            holder_info = HolderInfo(
                token=token,
                owner=req.owner,
                expires_at=expires_at,
                request_id=req.request_id
            )
            sem.holders[token] = holder_info

            events.append(Event(
                event=EventType.GRANTED,
                semaphore=sem.name,
                holder=req.owner,
                token=token,
                expires_at=expires_at,
                block_height=self.block_height,
                timestamp=block_time,
                details={"request_id": req.request_id, "promoted_from_queue": True}
            ))

            # Also update cached result for the queued request to GRANTED
            if req.request_id:
                self.seen[(req.owner, req.request_id)] = ("GRANTED", token, expires_at)

        return events

    def _create(self, tx: Transaction, block_time: int) -> Tuple[str, List[Event]]:
        if not tx.semaphore or tx.semaphore in self.sems:
            return "REJECTED_ALREADY_EXISTS", [Event(
                event=EventType.REJECTED,
                semaphore=tx.semaphore,
                holder=tx.sender,
                block_height=self.block_height,
                timestamp=block_time,
                details={"reason": "Semaphore already exists or invalid name"}
            )]

        capacity = tx.capacity if tx.capacity and tx.capacity > 0 else 1
        self.sems[tx.semaphore] = Semaphore(name=tx.semaphore, capacity=capacity)

        return "CREATED", [Event(
            event=EventType.CREATED,
            semaphore=tx.semaphore,
            holder=tx.sender,
            block_height=self.block_height,
            timestamp=block_time,
            details={"capacity": capacity}
        )]

    def _acquire(self, tx: Transaction, block_time: int) -> Tuple[Any, List[Event]]:
        sem = self.sems.get(tx.semaphore)
        if sem is None:
            return "REJECTED_NOT_FOUND", [Event(
                event=EventType.REJECTED,
                semaphore=tx.semaphore,
                holder=tx.sender,
                block_height=self.block_height,
                timestamp=block_time,
                details={"reason": f"Semaphore '{tx.semaphore}' not found"}
            )]

        lease_ms = tx.lease_ms if tx.lease_ms and tx.lease_ms > 0 else 5000

        # FIFO fairness: If queue is non-empty, must go to queue even if a slot just opened
        if len(sem.holders) < sem.capacity and not sem.queue:
            token = sem.next_token
            sem.next_token += 1
            expires_at = block_time + lease_ms
            sem.holders[token] = HolderInfo(
                token=token,
                owner=tx.sender,
                expires_at=expires_at,
                request_id=tx.request_id
            )
            return ("GRANTED", token, expires_at), [Event(
                event=EventType.GRANTED,
                semaphore=sem.name,
                holder=tx.sender,
                token=token,
                expires_at=expires_at,
                block_height=self.block_height,
                timestamp=block_time,
                details={"request_id": tx.request_id, "immediate": True}
            )]

        # Queue the request
        sem.queue.append(WaitRequest(
            owner=tx.sender,
            request_id=tx.request_id,
            lease_ms=lease_ms
        ))
        pos = len(sem.queue)
        return ("QUEUED", pos), [Event(
            event=EventType.QUEUED,
            semaphore=sem.name,
            holder=tx.sender,
            block_height=self.block_height,
            timestamp=block_time,
            details={"queue_position": pos, "request_id": tx.request_id}
        )]

    def _release(self, tx: Transaction, block_time: int) -> Tuple[str, List[Event]]:
        sem = self.sems.get(tx.semaphore)
        if sem is None or tx.token is None:
            return "REJECTED_NOT_FOUND", [Event(
                event=EventType.REJECTED,
                semaphore=tx.semaphore,
                holder=tx.sender,
                token=tx.token,
                block_height=self.block_height,
                timestamp=block_time,
                details={"reason": "Semaphore not found or token missing"}
            )]

        holder = sem.holders.get(tx.token)
        if holder is None or holder.owner != tx.sender:
            return "REJECTED_UNAUTHORIZED", [Event(
                event=EventType.REJECTED,
                semaphore=tx.semaphore,
                holder=tx.sender,
                token=tx.token,
                block_height=self.block_height,
                timestamp=block_time,
                details={"reason": "Token not active or sender is not holder"}
            )]

        del sem.holders[tx.token]
        events = [Event(
            event=EventType.RELEASED,
            semaphore=sem.name,
            holder=tx.sender,
            token=tx.token,
            block_height=self.block_height,
            timestamp=block_time,
            details={"request_id": tx.request_id}
        )]

        # Promote any waiters
        events.extend(self._promote_waiters(sem, block_time))
        return "RELEASED", events

    def _renew(self, tx: Transaction, block_time: int) -> Tuple[Any, List[Event]]:
        sem = self.sems.get(tx.semaphore)
        if sem is None or tx.token is None:
            return "REJECTED_NOT_FOUND", []

        holder = sem.holders.get(tx.token)
        if holder is None or holder.owner != tx.sender:
            return "REJECTED_UNAUTHORIZED", [Event(
                event=EventType.REJECTED,
                semaphore=tx.semaphore,
                holder=tx.sender,
                token=tx.token,
                block_height=self.block_height,
                timestamp=block_time,
                details={"reason": "Token not found or unauthorized"}
            )]

        lease_ms = tx.lease_ms if tx.lease_ms and tx.lease_ms > 0 else 5000
        new_expiry = block_time + lease_ms
        holder.expires_at = new_expiry

        return ("RENEWED", new_expiry), [Event(
            event=EventType.RENEWED,
            semaphore=sem.name,
            holder=tx.sender,
            token=tx.token,
            expires_at=new_expiry,
            block_height=self.block_height,
            timestamp=block_time,
            details={"request_id": tx.request_id}
        )]

    def get_state(self, semaphore_name: str) -> Optional[SemaphoreSnapshot]:
        s = self.sems.get(semaphore_name)
        if s is None:
            return None
        return s.to_snapshot()

    def get_all_states(self) -> Dict[str, SemaphoreSnapshot]:
        return {name: s.to_snapshot() for name, s in self.sems.items()}
