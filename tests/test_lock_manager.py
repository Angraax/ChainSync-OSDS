"""
Unit Tests for ChainSync Lock Manager (Task T1)
"""

import pytest
from core.models import Transaction, TransactionType, EventType
from core.lock_manager import LockManager
from core.crypto import KeyPair


def test_create_semaphore():
    lm = LockManager()
    kp = KeyPair.generate()
    tx = Transaction(
        type=TransactionType.CREATE,
        semaphore="db-mutex",
        capacity=1,
        request_id="req-1"
    ).sign(kp)

    res, events = lm.apply(tx, block_time=1000)
    assert res == "CREATED"
    assert len(events) == 1
    assert events[0].event == EventType.CREATED

    # Duplicate create fails
    tx2 = Transaction(
        type=TransactionType.CREATE,
        semaphore="db-mutex",
        capacity=1,
        request_id="req-2"
    ).sign(kp)
    res2, events2 = lm.apply(tx2, block_time=1000)
    assert res2 == "REJECTED_ALREADY_EXISTS"


def test_acquire_and_release_mutex():
    lm = LockManager()
    kp1 = KeyPair.generate()
    kp2 = KeyPair.generate()

    # Create mutex (capacity=1)
    lm.apply(Transaction(type=TransactionType.CREATE, semaphore="res-1", capacity=1).sign(kp1), block_time=1000)

    # Client 1 acquires
    tx_acq1 = Transaction(
        type=TransactionType.ACQUIRE,
        semaphore="res-1",
        lease_ms=5000,
        request_id="acq-1"
    ).sign(kp1)
    res1, events1 = lm.apply(tx_acq1, block_time=1000)
    status, token1, expiry1 = res1
    assert status == "GRANTED"
    assert token1 == 1
    assert expiry1 == 6000
    assert any(e.event == EventType.GRANTED and e.token == 1 for e in events1)

    # Client 2 tries to acquire -> should be QUEUED
    tx_acq2 = Transaction(
        type=TransactionType.ACQUIRE,
        semaphore="res-1",
        lease_ms=4000,
        request_id="acq-2"
    ).sign(kp2)
    res2, events2 = lm.apply(tx_acq2, block_time=1500)
    status2, pos = res2
    assert status2 == "QUEUED"
    assert pos == 1
    assert any(e.event == EventType.QUEUED for e in events2)

    # Client 1 releases -> Client 2 promoted with token 2!
    tx_rel1 = Transaction(
        type=TransactionType.RELEASE,
        semaphore="res-1",
        token=token1,
        request_id="rel-1"
    ).sign(kp1)
    res_rel, events_rel = lm.apply(tx_rel1, block_time=2000)
    assert res_rel == "RELEASED"
    # Should have RELEASED event for Client 1 and GRANTED event for Client 2
    assert any(e.event == EventType.RELEASED and e.token == 1 for e in events_rel)
    granted_promoted = [e for e in events_rel if e.event == EventType.GRANTED]
    assert len(granted_promoted) == 1
    assert granted_promoted[0].token == 2
    assert granted_promoted[0].holder == kp2.public_key_hex
    assert granted_promoted[0].expires_at == 2000 + 4000


def test_lease_expiry_by_block_time():
    lm = LockManager()
    kp = KeyPair.generate()

    lm.apply(Transaction(type=TransactionType.CREATE, semaphore="disk-io", capacity=1).sign(kp), block_time=1000)

    # Acquire with lease of 2000 ms (expires at 3000)
    tx = Transaction(type=TransactionType.ACQUIRE, semaphore="disk-io", lease_ms=2000, request_id="r1").sign(kp)
    lm.apply(tx, block_time=1000)

    state = lm.get_state("disk-io")
    assert len(state.holders) == 1

    # Advance time to 2500 -> still active
    lm.apply(Transaction(type=TransactionType.TICK), block_time=2500)
    state = lm.get_state("disk-io")
    assert len(state.holders) == 1

    # Advance time to 3001 -> expired!
    res, events = lm.apply(Transaction(type=TransactionType.TICK), block_time=3001)
    state = lm.get_state("disk-io")
    assert len(state.holders) == 0
    assert any(e.event == EventType.EXPIRED for e in events)


def test_idempotency_deduplication():
    lm = LockManager()
    kp = KeyPair.generate()
    lm.apply(Transaction(type=TransactionType.CREATE, semaphore="sem", capacity=1).sign(kp), block_time=1000)

    tx = Transaction(type=TransactionType.ACQUIRE, semaphore="sem", lease_ms=3000, request_id="idemp-1").sign(kp)
    res1, events1 = lm.apply(tx, block_time=1000)
    assert res1[0] == "GRANTED"
    assert len(events1) > 0

    # Repeat exact same transaction (e.g. network retry)
    res2, events2 = lm.apply(tx, block_time=1100)
    assert res2 == res1
    # No duplicate events emitted
    assert len(events2) == 0
    # Capacity still 1 holder, next_token still 2
    state = lm.get_state("sem")
    assert len(state.holders) == 1
    assert state.next_token == 2
