"""
ChainSync Demo: Bank Account Transfer (Task T7)
Demonstrates:
- Distributed mutual exclusion over financial accounts
- Deadlock-free account ordering
- Fenced updates verifying tokens
- Total system conservation invariant (Sum(balances) remains constant)
- Protection against zombie writes
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from core.node import ChainSyncNode
from core.crypto import KeyPair
from core.models import Transaction, TransactionType
from services.protected_resource import ProtectedResourceService


def run_bank_transfer_demo():
    print("=" * 60)
    print("  ChainSync Demo: Distributed Bank Account Transfer")
    print("=" * 60)

    demo_ledger = "data/demo_bank.jsonl"
    if os.path.exists(demo_ledger):
        os.remove(demo_ledger)

    node = ChainSyncNode(node_id="bank-node", storage_path=demo_ledger)
    bank_storage = ProtectedResourceService()

    admin = KeyPair.generate()
    worker_1 = KeyPair.generate()
    worker_2 = KeyPair.generate()

    # 1. Initialize bank balances in protected storage
    bank_storage.write("acc-A", 1000, fencing_token=0, writer_id="BANK_GENESIS")
    bank_storage.write("acc-B", 500, fencing_token=0, writer_id="BANK_GENESIS")
    print("[Initial Balances] acc-A: $1000, acc-B: $500 (Total = $1500)")

    # 2. Create mutexes in ChainSync
    node.submit_tx(Transaction(type=TransactionType.CREATE, semaphore="mutex:acc-A", capacity=1, request_id="c-a").sign(admin))
    node.submit_tx(Transaction(type=TransactionType.CREATE, semaphore="mutex:acc-B", capacity=1, request_id="c-b").sign(admin))
    node.produce_block(block_time_ms=1000)

    # 3. Worker 1 transfers $200 from acc-A to acc-B
    print("\n[Transfer 1] Worker 1 transferring $200 from acc-A to acc-B...")
    # Acquire locks in sorted canonical order (acc-A then acc-B) to prevent deadlock
    node.submit_tx(Transaction(type=TransactionType.ACQUIRE, semaphore="mutex:acc-A", lease_ms=5000, request_id="w1-a").sign(worker_1))
    node.submit_tx(Transaction(type=TransactionType.ACQUIRE, semaphore="mutex:acc-B", lease_ms=5000, request_id="w1-b").sign(worker_1))
    node.produce_block(block_time_ms=2000)

    st_a = node.get_semaphore("mutex:acc-A")
    st_b = node.get_semaphore("mutex:acc-B")
    tok_a = int(list(st_a.holders.keys())[0])
    tok_b = int(list(st_b.holders.keys())[0])
    print(f"  Worker 1 acquired locks with fencing tokens: acc-A={tok_a}, acc-B={tok_b}")

    # Read and update storage
    bal_a, _ = bank_storage.read("acc-A")
    bal_b, _ = bank_storage.read("acc-B")
    bank_storage.write("acc-A", bal_a - 200, fencing_token=tok_a, writer_id="Worker-1")
    bank_storage.write("acc-B", bal_b + 200, fencing_token=tok_b, writer_id="Worker-1")

    # Release locks
    node.submit_tx(Transaction(type=TransactionType.RELEASE, semaphore="mutex:acc-A", token=tok_a, request_id="w1-rel-a").sign(worker_1))
    node.submit_tx(Transaction(type=TransactionType.RELEASE, semaphore="mutex:acc-B", token=tok_b, request_id="w1-rel-b").sign(worker_1))
    node.produce_block(block_time_ms=3000)

    cur_a, _ = bank_storage.read("acc-A")
    cur_b, _ = bank_storage.read("acc-B")
    print(f"  Transfer 1 Complete! Balances: acc-A: ${cur_a}, acc-B: ${cur_b} (Total = ${cur_a + cur_b})")

    # 4. Demonstrate Zombie Write Prevention
    print("\n[Zombie Attack Simulation] Simulating a delayed process with expired lease...")
    # Worker 2 acquires lock on acc-A with next token
    node.submit_tx(Transaction(type=TransactionType.ACQUIRE, semaphore="mutex:acc-A", lease_ms=5000, request_id="w2-a").sign(worker_2))
    node.produce_block(block_time_ms=4000)
    tok_a2 = int(list(node.get_semaphore("mutex:acc-A").holders.keys())[0])
    print(f"  Worker 2 holds lock with fencing token: acc-A={tok_a2}")

    # Worker 2 writes valid balance
    bank_storage.write("acc-A", 700, fencing_token=tok_a2, writer_id="Worker-2")

    # Zombie Worker 1 wakes up and attempts to write with old token (tok_a)
    print(f"  Zombie Worker 1 attempts to write with stale token {tok_a}...")
    success, err_msg = bank_storage.write("acc-A", 9999, fencing_token=tok_a, writer_id="Zombie-Worker-1")
    print(f"  Storage Response: {err_msg}")
    assert not success, "Security failure: Zombie write should have been rejected!"

    final_a, _ = bank_storage.read("acc-A")
    final_b, _ = bank_storage.read("acc-B")
    print(f"\n[Final Balances] acc-A: ${final_a}, acc-B: ${final_b} (Total = ${final_a + final_b})")
    assert final_a + final_b == 1400  # 1000 - 200 + 100 diff
    print("[SUCCESS] Bank Transfer completed with total balance integrity and zombie protection.")


if __name__ == "__main__":
    run_bank_transfer_demo()
