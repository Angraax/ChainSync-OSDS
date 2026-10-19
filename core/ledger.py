"""
ChainSync Ledger (Task T2)
Append-only cryptographic blockchain ledger.
Features:
- Cryptographic hash-chain linking (prev_hash)
- Merkle root verification of transaction batches
- Append-only file persistence
- Tamper detection and chain validation
- Replay determinism: re-executing ledger log produces identical world state
- Merkle inclusion proof extraction for auditors and dashboard
"""

import os
import json
from typing import List, Optional, Tuple, Dict, Any
from core.models import Block, BlockHeader, Transaction, TransactionType
from core.crypto import sha256_hex, MerkleTree, canonical_json_bytes
from core.lock_manager import LockManager


class Ledger:
    def __init__(self, storage_path: str = "data/ledger.jsonl"):
        self.storage_path = storage_path
        self.blocks: List[Block] = []
        os.makedirs(os.path.dirname(os.path.abspath(self.storage_path)), exist_ok=True)
        self._load_from_disk()

        # If empty, initialize genesis block
        if not self.blocks:
            self._create_genesis_block()

    def _create_genesis_block(self):
        genesis_header = BlockHeader(
            height=0,
            prev_hash="0" * 64,
            merkle_root=sha256_hex(b"GENESIS_MERKLE_ROOT"),
            timestamp=1700000000000,
            proposer="GENESIS"
        )
        genesis_block = Block(
            header=genesis_header,
            transactions=[],
            block_hash=genesis_header.header_hash()
        )
        self.blocks.append(genesis_block)
        self._persist_block_to_disk(genesis_block)

    def _load_from_disk(self):
        if not os.path.exists(self.storage_path):
            return
        with open(self.storage_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    block_data = json.loads(line)
                    blk = Block.model_validate(block_data)
                    self.blocks.append(blk)

    def _persist_block_to_disk(self, block: Block):
        with open(self.storage_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(block.model_dump()) + "\n")

    @property
    def latest_block(self) -> Block:
        return self.blocks[-1]

    @property
    def height(self) -> int:
        return self.latest_block.header.height

    def append_block(self, block: Block) -> Tuple[bool, Optional[str]]:
        """
        Validates candidate block against ledger rules and appends if valid.
        """
        last = self.latest_block

        # 1. Height sequence check
        if block.header.height != last.header.height + 1:
            return False, f"Invalid height: expected {last.header.height + 1}, got {block.header.height}"

        # 2. Previous hash linking check
        if block.header.prev_hash != last.block_hash:
            return False, f"Broken hash chain: expected prev_hash {last.block_hash}, got {block.header.prev_hash}"

        # 3. Monotonic block time check
        if block.header.timestamp < last.header.timestamp:
            return False, f"Block timestamp {block.header.timestamp} is earlier than previous {last.header.timestamp}"

        # 4. Merkle root recalculation and verification
        tx_hashes = [tx.tx_hash() for tx in block.transactions]
        calculated_merkle = MerkleTree(tx_hashes).root
        if block.header.merkle_root != calculated_merkle:
            return False, f"Merkle root mismatch: expected {calculated_merkle}, got {block.header.merkle_root}"

        # 5. Header hash integrity
        calculated_hash = block.header.header_hash()
        if block.block_hash != calculated_hash:
            return False, f"Block hash mismatch: header hash {calculated_hash} != {block.block_hash}"

        # 6. Cryptographic signature check for all non-TICK transactions
        for tx in block.transactions:
            if tx.type != TransactionType.TICK:
                if not tx.verify():
                    return False, f"Invalid transaction signature in tx {tx.request_id} from {tx.sender}"

        # Passed all validation checks
        self.blocks.append(block)
        self._persist_block_to_disk(block)
        return True, None

    def verify_integrity(self) -> Tuple[bool, Optional[str]]:
        """
        Audits the entire ledger from Genesis to tip.
        Detects any tampering with blocks, hashes, or transaction contents.
        """
        if not self.blocks:
            return False, "Ledger is empty"

        # Check genesis
        if self.blocks[0].header.height != 0 or self.blocks[0].header.prev_hash != "0" * 64:
            return False, "Corrupted genesis block"

        for i in range(1, len(self.blocks)):
            prev = self.blocks[i - 1]
            curr = self.blocks[i]

            # Check hash chain link
            if curr.header.prev_hash != prev.block_hash:
                return False, f"Broken link at block #{curr.header.height}: prev_hash does not match block #{prev.header.height}"

            # Check header hash calculation
            if curr.block_hash != curr.header.header_hash():
                return False, f"Tampered block hash at block #{curr.header.height}"

            # Check Merkle tree calculation
            tx_hashes = [tx.tx_hash() for tx in curr.transactions]
            expected_merkle = MerkleTree(tx_hashes).root
            if curr.header.merkle_root != expected_merkle:
                return False, f"Tampered transactions detected in block #{curr.header.height}"

        return True, None

    def replay(self, target_lock_manager: Optional[LockManager] = None) -> LockManager:
        """
        Re-executes all transactions from block 0 onwards onto a fresh LockManager.
        Guarantees deterministic state reconstruction.
        """
        lm = target_lock_manager or LockManager()
        for block in self.blocks:
            btime = block.header.timestamp
            bheight = block.header.height
            for tx in block.transactions:
                lm.apply(tx, block_time=btime, block_height=bheight)
        return lm

    def get_merkle_proof(self, height: int, tx_hash: str) -> Optional[Dict[str, Any]]:
        """
        Generates Merkle inclusion proof for a given transaction within a block.
        Used by the Block Explorer and client light-verification.
        """
        if height < 0 or height >= len(self.blocks):
            return None

        block = self.blocks[height]
        tx_hashes = [tx.tx_hash() for tx in block.transactions]
        if tx_hash not in tx_hashes:
            return None

        idx = tx_hashes.index(tx_hash)
        merkle = MerkleTree(tx_hashes)
        proof = merkle.get_proof(idx)

        return {
            "block_height": height,
            "tx_hash": tx_hash,
            "merkle_root": block.header.merkle_root,
            "proof": proof
        }
