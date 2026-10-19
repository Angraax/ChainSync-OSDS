"""
ChainSync Demo: Producer-Consumer with Counting Semaphores (Task T7)
Classic Bounded Buffer Synchronization.
Demonstrates:
- Counting semaphores for resource tracking
- Binary semaphore (mutex) for buffer mutual exclusion
- Coordination between producer and consumer processes
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from core.node import ChainSyncNode
from core.crypto import KeyPair
from core.models import Transaction, TransactionType


def run_producer_consumer_demo():
    print("=" * 60)
    print("  ChainSync Demo: Producer-Consumer (Bounded Buffer)")
    print("=" * 60)

    demo_ledger = "data/demo_prod_cons.jsonl"
    if os.path.exists(demo_ledger):
        os.remove(demo_ledger)

    node = ChainSyncNode(node_id="pc-node", storage_path=demo_ledger)

    admin = KeyPair.generate()
    producer = KeyPair.generate()
    consumer = KeyPair.generate()

    buffer_capacity = 3
    shared_buffer = []

    # 1. Initialize Semaphores
    # 'empty_slots': counting semaphore with capacity = buffer_capacity (3)
    # 'mutex_buffer': mutex (capacity 1)
    print(f"\n[Step 1] Initializing Bounded Buffer (Capacity = {buffer_capacity})...")
    node.submit_tx(Transaction(type=TransactionType.CREATE, semaphore="sem:empty_slots", capacity=buffer_capacity, request_id="c-empty").sign(admin))
    node.submit_tx(Transaction(type=TransactionType.CREATE, semaphore="sem:mutex_buffer", capacity=1, request_id="c-mutex").sign(admin))
    node.produce_block(block_time_ms=1000)
    print("[OK] Semaphores created.")

    # 2. Producer produces 3 items filling the buffer
    print("\n[Step 2] Producer producing items until buffer is full...")
    sim_time = 2000
    producer_tokens = []

    for item_val in [101, 102, 103]:
        # Producer acquires empty slot
        node.submit_tx(Transaction(type=TransactionType.ACQUIRE, semaphore="sem:empty_slots", lease_ms=10000, request_id=f"p-empty-{item_val}").sign(producer))
        # Producer acquires buffer mutex
        node.submit_tx(Transaction(type=TransactionType.ACQUIRE, semaphore="sem:mutex_buffer", lease_ms=5000, request_id=f"p-mut-{item_val}").sign(producer))
        sim_time += 500
        node.produce_block(block_time_ms=sim_time)

        # Append to buffer
        shared_buffer.append(item_val)
        mut_st = node.get_semaphore("sem:mutex_buffer")
        mut_tok = int(list(mut_st.holders.keys())[0])

        empty_st = node.get_semaphore("sem:empty_slots")
        print(f"  Producer produced item {item_val} | Buffer: {shared_buffer} | Active Slots Held: {len(empty_st.holders)}/{buffer_capacity}")

        # Release mutex
        node.submit_tx(Transaction(type=TransactionType.RELEASE, semaphore="sem:mutex_buffer", token=mut_tok, request_id=f"p-rel-mut-{item_val}").sign(producer))
        sim_time += 500
        node.produce_block(block_time_ms=sim_time)

    # 3. Buffer is full! Producer tries to produce a 4th item -> gets QUEUED!
    print("\n[Step 3] Buffer is now FULL. Producer attempts to produce 4th item (104)...")
    node.submit_tx(Transaction(type=TransactionType.ACQUIRE, semaphore="sem:empty_slots", lease_ms=10000, request_id="p-empty-104").sign(producer))
    sim_time += 500
    node.produce_block(block_time_ms=sim_time)

    empty_st = node.get_semaphore("sem:empty_slots")
    print(f"  Empty slots queue length: {len(empty_st.queue)} (Request is blocked/queued waiting for space!)")
    assert len(empty_st.queue) == 1, "Producer request should be queued"

    # 4. Consumer consumes 1 item -> frees a slot, automatically unblocking producer!
    print("\n[Step 4] Consumer consumes 1 item from buffer...")
    # Consumer acquires mutex
    node.submit_tx(Transaction(type=TransactionType.ACQUIRE, semaphore="sem:mutex_buffer", lease_ms=5000, request_id="c-mut-1").sign(consumer))
    sim_time += 500
    node.produce_block(block_time_ms=sim_time)

    c_mut_tok = int(list(node.get_semaphore("sem:mutex_buffer").holders.keys())[0])
    consumed_item = shared_buffer.pop(0)
    print(f"  Consumer removed item {consumed_item} | Buffer: {shared_buffer}")

    # Release consumer mutex
    node.submit_tx(Transaction(type=TransactionType.RELEASE, semaphore="sem:mutex_buffer", token=c_mut_tok, request_id="c-rel-mut-1").sign(consumer))

    # Release 1 empty slot token to wake up waiting producer
    oldest_slot_token = sorted([int(k) for k in empty_st.holders.keys()])[0]
    node.submit_tx(Transaction(type=TransactionType.RELEASE, semaphore="sem:empty_slots", token=oldest_slot_token, request_id="rel-slot-1").sign(producer))
    sim_time += 500
    node.produce_block(block_time_ms=sim_time)

    empty_st_after = node.get_semaphore("sem:empty_slots")
    print(f"  Slot released! Queue length now: {len(empty_st_after.queue)} (Blocked producer promoted into available slot!)")
    assert len(empty_st_after.queue) == 0, "Queued producer should now be granted"

    print("\n[SUCCESS] Producer-Consumer bounded buffer coordination verified.")


if __name__ == "__main__":
    run_producer_consumer_demo()
