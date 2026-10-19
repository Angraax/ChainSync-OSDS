"""
Tests for Ledger & Merkle Verification (Task T2) and Protected Resource Fencing (Task T5)
"""

import os
import shutil
import pytest
from core.models import Block, Transaction, TransactionType
from core.ledger import Ledger
from core.crypto import KeyPair, MerkleTree
from core.lock_manager import LockManager
from services.protected_resource import ProtectedResourceService


def test_ledger_append_and_merkle_proof(tmp_path):
    storage_file = str(tmp_path / "test_ledger.jsonl")
    ledger = Ledger(storage_path=storage_file)

    kp1 = KeyPair.generate()
    kp2 = KeyPair.generate()

    tx1 = Transaction(type=TransactionType.CREATE, semaphore="vault", capacity=1, request_id="tx1").sign(kp1)
    tx2 = Transaction(type=TransactionType.ACQUIRE, semaphore="vault", lease_ms=5000, request_id="tx2").sign(kp2)

    block1 = Block.create(
        height=1,
        prev_hash=ledger.latest_block.block_hash,
        timestamp=1700000001000,
        proposer="leader-1",
        transactions=[tx1, tx2]
    )

    success, err = ledger.append_block(block1)
    assert success, f"Failed to append block: {err}"
    assert ledger.height == 1

    # Verify integrity
    is_valid, err_msg = ledger.verify_integrity()
    assert is_valid, f"Ledger integrity failed: {err_msg}"

    # Test Merkle inclusion proof
    proof_data = ledger.get_merkle_proof(height=1, tx_hash=tx1.tx_hash())
    assert proof_data is not None
    assert MerkleTree.verify_proof(
        leaf_hash=tx1.tx_hash(),
        proof=proof_data["proof"],
        expected_root=block1.header.merkle_root
    )


def test_ledger_tamper_detection(tmp_path):
    storage_file = str(tmp_path / "tamper_ledger.jsonl")
    ledger = Ledger(storage_path=storage_file)

    kp = KeyPair.generate()
    tx = Transaction(type=TransactionType.CREATE, semaphore="safe", capacity=1, request_id="tx-safe").sign(kp)

    blk = Block.create(
        height=1,
        prev_hash=ledger.latest_block.block_hash,
        timestamp=1700000002000,
        proposer="leader-1",
        transactions=[tx]
    )
    ledger.append_block(blk)

    # Tamper with storage file: modify transaction in block 1
    with open(storage_file, "r", encoding="utf-8") as f:
        lines = f.readlines()

    # Alter payload in line 1
    lines[1] = lines[1].replace("safe", "corrupted_safe")
    with open(storage_file, "w", encoding="utf-8") as f:
        f.writelines(lines)

    # Reload ledger and verify tamper detection
    tampered_ledger = Ledger(storage_path=storage_file)
    is_valid, err_msg = tampered_ledger.verify_integrity()
    assert not is_valid
    assert "Tampered" in err_msg or "mismatch" in err_msg


def test_protected_resource_fencing_blocks_zombie_writes():
    resource = ProtectedResourceService()

    # Process 1 acquires lock, gets fencing token 10
    ok, msg = resource.write(key="account:42", value={"balance": 500}, fencing_token=10, writer_id="P1")
    assert ok
    val, tok = resource.read("account:42")
    assert val == {"balance": 500}
    assert tok == 10

    # Process 1 suffers a long GC pause / network split.
    # Its lease expires and Process 2 acquires lock, gets fencing token 11!
    ok2, msg2 = resource.write(key="account:42", value={"balance": 750}, fencing_token=11, writer_id="P2")
    assert ok2
    val2, tok2 = resource.read("account:42")
    assert val2 == {"balance": 750}
    assert tok2 == 11

    # Now zombie Process 1 wakes up, unaware it was preempted, and attempts to write with token 10
    zombie_ok, zombie_msg = resource.write(key="account:42", value={"balance": 1000}, fencing_token=10, writer_id="P1")
    assert not zombie_ok
    assert "Zombie write prevented" in zombie_msg

    # Final storage state remains uncorrupted by the zombie write
    final_val, final_tok = resource.read("account:42")
    assert final_val == {"balance": 750}
    assert final_tok == 11
