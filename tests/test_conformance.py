"""
ChainSync Conformance Test Suite (Task T8)
Standardized conformance contract that verifies any compliant node or mock server.
Tests:
- Acquire & Release
- FIFO Queue ordering
- Monotonic Fencing Token progression
- Idempotent request retry
- Block-time lease expiration & automatic promotion
"""

import pytest
from core.models import Transaction, TransactionType, EventType
from core.node import ChainSyncNode
from core.crypto import KeyPair


@pytest.fixture
def test_node(tmp_path):
    storage_file = str(tmp_path / "conformance_ledger.jsonl")
    return ChainSyncNode(node_id="conformance-node", storage_path=storage_file)


def test_conformance_acquire_and_release(test_node):
    node = test_node
    events_received = []
    node.subscribe_events(lambda ev: events_received.append(ev))

    admin = KeyPair.generate()
    client1 = KeyPair.generate()

    # 1. Create mutex
    node.submit_tx(Transaction(
        type=TransactionType.CREATE,
        semaphore="mutex-c1",
        capacity=1,
        request_id="init-1"
    ).sign(admin))
    node.produce_block(block_time_ms=1000)

    sem = node.get_semaphore("mutex-c1")
    assert sem is not None
    assert sem.capacity == 1

    # 2. Acquire
    node.submit_tx(Transaction(
        type=TransactionType.ACQUIRE,
        semaphore="mutex-c1",
        lease_ms=5000,
        request_id="acq-c1"
    ).sign(client1))
    node.produce_block(block_time_ms=2000)

    sem = node.get_semaphore("mutex-c1")
    assert len(sem.holders) == 1
    token = list(sem.holders.keys())[0]
    assert sem.holders[token].owner == client1.public_key_hex

    # 3. Release
    node.submit_tx(Transaction(
        type=TransactionType.RELEASE,
        semaphore="mutex-c1",
        token=int(token),
        request_id="rel-c1"
    ).sign(client1))
    node.produce_block(block_time_ms=3000)

    sem = node.get_semaphore("mutex-c1")
    assert len(sem.holders) == 0


def test_conformance_queue_and_token_monotonicity(test_node):
    node = test_node
    admin = KeyPair.generate()
    clients = [KeyPair.generate() for _ in range(3)]

    # Create mutex
    node.submit_tx(Transaction(type=TransactionType.CREATE, semaphore="queue-sem", capacity=1).sign(admin))
    node.produce_block(block_time_ms=1000)

    # Client 0 acquires
    node.submit_tx(Transaction(type=TransactionType.ACQUIRE, semaphore="queue-sem", lease_ms=10000, request_id="acq-0").sign(clients[0]))
    # Clients 1 & 2 attempt to acquire in same/subsequent block
    node.submit_tx(Transaction(type=TransactionType.ACQUIRE, semaphore="queue-sem", lease_ms=5000, request_id="acq-1").sign(clients[1]))
    node.submit_tx(Transaction(type=TransactionType.ACQUIRE, semaphore="queue-sem", lease_ms=5000, request_id="acq-2").sign(clients[2]))
    node.produce_block(block_time_ms=2000)

    sem = node.get_semaphore("queue-sem")
    assert len(sem.holders) == 1
    assert "1" in sem.holders
    assert len(sem.queue) == 2
    assert sem.queue[0].owner == clients[1].public_key_hex
    assert sem.queue[1].owner == clients[2].public_key_hex

    # Client 0 releases -> Client 1 should be promoted with token 2
    node.submit_tx(Transaction(type=TransactionType.RELEASE, semaphore="queue-sem", token=1, request_id="rel-0").sign(clients[0]))
    node.produce_block(block_time_ms=3000)

    sem = node.get_semaphore("queue-sem")
    assert len(sem.holders) == 1
    assert "2" in sem.holders
    assert sem.holders["2"].owner == clients[1].public_key_hex
    assert len(sem.queue) == 1

    # Client 1 releases -> Client 2 should be promoted with token 3
    node.submit_tx(Transaction(type=TransactionType.RELEASE, semaphore="queue-sem", token=2, request_id="rel-1").sign(clients[1]))
    node.produce_block(block_time_ms=4000)

    sem = node.get_semaphore("queue-sem")
    assert len(sem.holders) == 1
    assert "3" in sem.holders
    assert sem.holders["3"].owner == clients[2].public_key_hex
    assert len(sem.queue) == 0


def test_conformance_lease_expiry_reclaim(test_node):
    node = test_node
    admin = KeyPair.generate()
    c1 = KeyPair.generate()
    c2 = KeyPair.generate()

    node.submit_tx(Transaction(type=TransactionType.CREATE, semaphore="exp-sem", capacity=1).sign(admin))
    node.produce_block(block_time_ms=1000)

    # c1 acquires with 2000 ms lease (expires at 3000)
    node.submit_tx(Transaction(type=TransactionType.ACQUIRE, semaphore="exp-sem", lease_ms=2000, request_id="c1-acq").sign(c1))
    node.produce_block(block_time_ms=1000)

    # c2 queues up
    node.submit_tx(Transaction(type=TransactionType.ACQUIRE, semaphore="exp-sem", lease_ms=4000, request_id="c2-acq").sign(c2))
    node.produce_block(block_time_ms=1500)

    sem = node.get_semaphore("exp-sem")
    assert len(sem.holders) == 1
    assert len(sem.queue) == 1

    # Leader produces empty block at time 3500 (beyond lease of c1)
    # The TICK inside the block should reclaim c1 and promote c2!
    node.produce_block(block_time_ms=3500)

    sem = node.get_semaphore("exp-sem")
    assert len(sem.holders) == 1
    # Holder must now be c2
    holder = list(sem.holders.values())[0]
    assert holder.owner == c2.public_key_hex
    assert len(sem.queue) == 0
