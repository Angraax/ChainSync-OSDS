"""
ChainSync Property and Invariant Tests (Task T4)
Verifies:
1. Mutual Exclusion: len(holders) <= capacity across all states
2. Token Monotonicity: Fencing tokens strictly increase
3. FIFO Fairness: Waiting clients are promoted in strict queue order
4. Deterministic Replay: Re-executing random histories produces bit-identical states
"""

import random
from typing import List, Tuple
from core.models import Transaction, TransactionType, EventType
from core.lock_manager import LockManager
from core.crypto import KeyPair


def test_property_invariants_fuzzing():
    """
    Simulates hundreds of randomized operations across 5 clients and 2 semaphores.
    Checks mutual exclusion and token monotonicity after every single transaction.
    """
    random.seed(42)
    lm = LockManager()

    # Setup clients
    clients = [KeyPair.generate() for _ in range(5)]
    semaphores = {"mutex-1": 1, "counting-3": 3}

    # Initialize semaphores
    init_time = 1000
    for name, cap in semaphores.items():
        lm.apply(Transaction(
            type=TransactionType.CREATE,
            semaphore=name,
            capacity=cap,
            request_id=f"init-{name}"
        ).sign(clients[0]), block_time=init_time)

    current_time = init_time
    last_tokens = {name: 0 for name in semaphores}
    active_tokens = {name: {} for name in semaphores}  # token -> owner

    for step in range(500):
        # Time advances monotonically
        current_time += random.randint(50, 400)
        action = random.choice(["ACQUIRE", "RELEASE", "RENEW", "TICK"])
        sem_name = random.choice(list(semaphores.keys()))
        client = random.choice(clients)
        req_id = f"req-{step}"

        if action == "ACQUIRE":
            tx = Transaction(
                type=TransactionType.ACQUIRE,
                semaphore=sem_name,
                lease_ms=random.randint(1000, 3000),
                request_id=req_id
            ).sign(client)
        elif action == "RELEASE":
            # Pick a token held by this client, or random
            held = [t for t, o in active_tokens[sem_name].items() if o == client.public_key_hex]
            token = held[0] if held else random.randint(1, 100)
            tx = Transaction(
                type=TransactionType.RELEASE,
                semaphore=sem_name,
                token=token,
                request_id=req_id
            ).sign(client)
        elif action == "RENEW":
            held = [t for t, o in active_tokens[sem_name].items() if o == client.public_key_hex]
            token = held[0] if held else random.randint(1, 100)
            tx = Transaction(
                type=TransactionType.RENEW,
                semaphore=sem_name,
                token=token,
                lease_ms=random.randint(1000, 2000),
                request_id=req_id
            ).sign(client)
        else:  # TICK
            tx = Transaction(type=TransactionType.TICK, request_id=req_id)

        res, events = lm.apply(tx, block_time=current_time)

        # Track tokens & events
        for ev in events:
            if ev.event == EventType.GRANTED:
                # Invariant: Token Monotonicity
                assert ev.token > last_tokens[ev.semaphore], (
                    f"Token monotonicity violated for {ev.semaphore}: {ev.token} <= {last_tokens[ev.semaphore]}"
                )
                last_tokens[ev.semaphore] = ev.token
                active_tokens[ev.semaphore][ev.token] = ev.holder

            elif ev.event in (EventType.RELEASED, EventType.EXPIRED):
                active_tokens[ev.semaphore].pop(ev.token, None)

        # Invariant: Mutual Exclusion (holders <= capacity)
        for s_name, max_cap in semaphores.items():
            st = lm.get_state(s_name)
            assert len(st.holders) <= max_cap, (
                f"Mutual exclusion violated for {s_name}: {len(st.holders)} > {max_cap}"
            )


def test_fifo_fairness_property():
    """
    Verifies that queued clients are served in exact strict FIFO order.
    """
    lm = LockManager()
    owner = KeyPair.generate()
    # Mutex: capacity 1
    lm.apply(Transaction(type=TransactionType.CREATE, semaphore="fifo-sem", capacity=1).sign(owner), block_time=1000)

    # 1st client acquires
    c0 = KeyPair.generate()
    lm.apply(Transaction(type=TransactionType.ACQUIRE, semaphore="fifo-sem", lease_ms=10000, request_id="c0").sign(c0), block_time=1000)

    # 4 clients queue up in order: c1, c2, c3, c4
    queued_clients = [KeyPair.generate() for _ in range(4)]
    for i, c in enumerate(queued_clients, start=1):
        lm.apply(Transaction(type=TransactionType.ACQUIRE, semaphore="fifo-sem", lease_ms=5000, request_id=f"c{i}").sign(c), block_time=1000 + i*100)

    # Verify queue contains exact sequence
    st = lm.get_state("fifo-sem")
    assert [w.owner for w in st.queue] == [c.public_key_hex for c in queued_clients]

    # As each client releases, verify promotions follow exact FIFO sequence
    current_token = 1
    current_owner = c0
    current_time = 2000

    for expected_promoted in queued_clients:
        res, events = lm.apply(Transaction(
            type=TransactionType.RELEASE,
            semaphore="fifo-sem",
            token=current_token,
            request_id=f"rel-{current_token}"
        ).sign(current_owner), block_time=current_time)

        # Check who was granted
        granted = [e for e in events if e.event == EventType.GRANTED]
        assert len(granted) == 1
        assert granted[0].holder == expected_promoted.public_key_hex

        current_token = granted[0].token
        current_owner = expected_promoted
        current_time += 500


def test_deterministic_replay():
    """
    Verifies that applying the exact same sequence of transactions and block times
    to a separate fresh LockManager generates bit-identical state.
    """
    random.seed(12345)
    lm1 = LockManager()
    lm2 = LockManager()

    clients = [KeyPair.generate() for _ in range(3)]
    tx_history: List[Tuple[Transaction, int]] = []

    # CREATE
    t0 = Transaction(type=TransactionType.CREATE, semaphore="rep-mutex", capacity=2).sign(clients[0])
    tx_history.append((t0, 1000))

    sim_time = 1000
    for i in range(100):
        sim_time += random.randint(100, 300)
        c = random.choice(clients)
        op = random.choice(["ACQ", "TICK"])
        if op == "ACQ":
            tx = Transaction(type=TransactionType.ACQUIRE, semaphore="rep-mutex", lease_ms=1000, request_id=f"r-{i}").sign(c)
        else:
            tx = Transaction(type=TransactionType.TICK, request_id=f"tick-{i}")
        tx_history.append((tx, sim_time))

    # Apply to lm1
    for tx, btime in tx_history:
        lm1.apply(tx, btime)

    # Apply to lm2
    for tx, btime in tx_history:
        lm2.apply(tx, btime)

    s1 = lm1.get_state("rep-mutex")
    s2 = lm2.get_state("rep-mutex")

    assert s1.model_dump() == s2.model_dump(), "Replay did not produce identical state!"
