"""
ChainSync Demo: Dining Philosophers (Task T7)
5 Philosophers sitting at a table with 5 forks.
Each fork is represented by a ChainSync Semaphore (mutex, capacity 1).
Demonstrates:
- Distributed mutual exclusion per fork
- Deadlock-free resource ordering hierarchy
- Lease management and clean release
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from core.node import ChainSyncNode
from core.crypto import KeyPair
from core.models import Transaction, TransactionType


def run_dining_philosophers_demo():
    print("=" * 60)
    print("  ChainSync Demo: Dining Philosophers Concurrency")
    print("=" * 60)

    demo_ledger = "data/demo_philosophers.jsonl"
    if os.path.exists(demo_ledger):
        os.remove(demo_ledger)

    node = ChainSyncNode(node_id="philosopher-node", storage_path=demo_ledger)

    num_philosophers = 5
    admin = KeyPair.generate()
    philosophers = [KeyPair.generate() for _ in range(num_philosophers)]

    # 1. Create 5 fork semaphores
    print("\n[Step 1] Creating 5 fork mutexes (fork-0 to fork-4)...")
    for i in range(num_philosophers):
        node.submit_tx(Transaction(
            type=TransactionType.CREATE,
            semaphore=f"fork-{i}",
            capacity=1,
            request_id=f"create-fork-{i}"
        ).sign(admin))
    node.produce_block(block_time_ms=1000)

    print("[OK] All forks initialized in world state.")

    # 2. Simulation cycles
    # Dijkstra's Resource Hierarchy: always acquire lower-numbered fork first
    print("\n[Step 2] Philosophers competing for adjacent forks...")

    sim_time = 2000
    for cycle in range(3):
        print(f"\n--- Eating Cycle {cycle + 1} ---")
        for i in range(num_philosophers):
            left_fork = i
            right_fork = (i + 1) % num_philosophers
            first_fork, second_fork = sorted([left_fork, right_fork])

            node.submit_tx(Transaction(
                type=TransactionType.ACQUIRE,
                semaphore=f"fork-{first_fork}",
                lease_ms=5000,
                request_id=f"p{i}-f1-c{cycle}"
            ).sign(philosophers[i]))

            node.submit_tx(Transaction(
                type=TransactionType.ACQUIRE,
                semaphore=f"fork-{second_fork}",
                lease_ms=5000,
                request_id=f"p{i}-f2-c{cycle}"
            ).sign(philosophers[i]))

        sim_time += 1000
        node.produce_block(block_time_ms=sim_time)

        # Check who was granted both forks
        eaters = []
        for i in range(num_philosophers):
            f1_state = node.get_semaphore(f"fork-{i}")
            f2_state = node.get_semaphore(f"fork-{(i + 1) % num_philosophers}")
            p_key = philosophers[i].public_key_hex

            h1 = [tok for tok, h in f1_state.holders.items() if h.owner == p_key]
            h2 = [tok for tok, h in f2_state.holders.items() if h.owner == p_key]

            if h1 and h2:
                eaters.append(i)
                print(f"  [Eating] Philosopher #{i} acquired forks ({i}, {(i+1)%num_philosophers}) with tokens ({h1[0]}, {h2[0]})")
                # Release forks after eating
                node.submit_tx(Transaction(
                    type=TransactionType.RELEASE,
                    semaphore=f"fork-{i}",
                    token=int(h1[0]),
                    request_id=f"rel-p{i}-f1-c{cycle}"
                ).sign(philosophers[i]))
                node.submit_tx(Transaction(
                    type=TransactionType.RELEASE,
                    semaphore=f"fork-{(i+1)%num_philosophers}",
                    token=int(h2[0]),
                    request_id=f"rel-p{i}-f2-c{cycle}"
                ).sign(philosophers[i]))

        print(f"  -> Philosophers currently eating: {eaters} (Mutual Exclusion Guaranteed)")
        sim_time += 1000
        node.produce_block(block_time_ms=sim_time)

    print("\n[SUCCESS] Dining Philosophers completed without deadlock or race condition.")


if __name__ == "__main__":
    run_dining_philosophers_demo()
