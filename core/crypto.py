"""
ChainSync Cryptography Module
Handles Ed25519 key generation, transaction signing, signature verification,
SHA-256 hashing, and Merkle tree generation with inclusion proofs.
"""

import hashlib
import json
from typing import List, Tuple, Optional, Dict, Any
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives import serialization
from cryptography.exceptions import InvalidSignature


def sha256_hex(data: bytes) -> str:
    """Computes SHA-256 hash returned as lowercase hex string."""
    return hashlib.sha256(data).hexdigest()


def canonical_json_bytes(obj: Any) -> bytes:
    """
    Serializes a dictionary or list into deterministic, canonical JSON bytes
    (sorted keys, no extraneous whitespace, UTF-8 encoded).
    """
    return json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('utf-8')


class KeyPair:
    """Manages an Ed25519 private/public keypair."""
    def __init__(self, private_key: Optional[ed25519.Ed25519PrivateKey] = None):
        if private_key is None:
            self.private_key = ed25519.Ed25519PrivateKey.generate()
        else:
            self.private_key = private_key
        self.public_key = self.private_key.public_key()

    @classmethod
    def generate(cls) -> "KeyPair":
        return cls()

    @property
    def public_key_hex(self) -> str:
        raw_bytes = self.public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw
        )
        return raw_bytes.hex()

    @property
    def private_key_hex(self) -> str:
        raw_bytes = self.private_key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption()
        )
        return raw_bytes.hex()

    @classmethod
    def from_private_hex(cls, private_hex: str) -> "KeyPair":
        raw_bytes = bytes.fromhex(private_hex)
        priv = ed25519.Ed25519PrivateKey.from_private_bytes(raw_bytes)
        return cls(priv)

    def sign(self, message: bytes) -> str:
        """Signs message bytes and returns hex string of signature."""
        sig = self.private_key.sign(message)
        return sig.hex()


def verify_signature(public_key_hex: str, message: bytes, signature_hex: str) -> bool:
    """Verifies an Ed25519 signature against public key hex and message bytes."""
    try:
        pub_bytes = bytes.fromhex(public_key_hex)
        sig_bytes = bytes.fromhex(signature_hex)
        pub = ed25519.Ed25519PublicKey.from_public_bytes(pub_bytes)
        pub.verify(sig_bytes, message)
        return True
    except (InvalidSignature, ValueError, Exception):
        return False


class MerkleTree:
    """
    Constructs a cryptographic Merkle tree from transaction hashes
    and produces/verifies inclusion proofs (O(log N)).
    """
    def __init__(self, leaf_hashes: List[str]):
        # Leaves are SHA256 hashes of transactions
        if not leaf_hashes:
            self.leaves = [sha256_hex(b"EMPTY_LEAF")]
        else:
            self.leaves = list(leaf_hashes)
        self.levels: List[List[str]] = [self.leaves]
        self._build_tree()

    def _build_tree(self):
        current_level = self.leaves
        while len(current_level) > 1:
            next_level = []
            for i in range(0, len(current_level), 2):
                left = current_level[i]
                # If odd number of nodes, duplicate the last one (standard Bitcoin/Ethereum approach)
                right = current_level[i + 1] if i + 1 < len(current_level) else left
                combined = bytes.fromhex(left) + bytes.fromhex(right)
                parent_hash = sha256_hex(combined)
                next_level.append(parent_hash)
            self.levels.append(next_level)
            current_level = next_level

    @property
    def root(self) -> str:
        """Returns the Merkle root hash."""
        return self.levels[-1][0]

    def get_proof(self, leaf_index: int) -> List[Dict[str, str]]:
        """
        Generates an audit path / inclusion proof for the leaf at leaf_index.
        Each element in the proof indicates sibling hash and direction ('left' or 'right').
        """
        if leaf_index < 0 or leaf_index >= len(self.leaves):
            raise IndexError("Leaf index out of bounds")

        proof = []
        idx = leaf_index
        for level in self.levels[:-1]:
            is_right = (idx % 2 == 1)
            sibling_idx = idx - 1 if is_right else idx + 1
            if sibling_idx < len(level):
                sibling_hash = level[sibling_idx]
            else:
                sibling_hash = level[idx]  # Duplicated leaf
            proof.append({
                "position": "left" if is_right else "right",
                "hash": sibling_hash
            })
            idx //= 2
        return proof

    @staticmethod
    def verify_proof(leaf_hash: str, proof: List[Dict[str, str]], expected_root: str) -> bool:
        """
        Verifies if leaf_hash combined with proof hashes computes to expected_root.
        """
        current_hash = leaf_hash
        for step in proof:
            sibling = step["hash"]
            if step["position"] == "right":
                combined = bytes.fromhex(current_hash) + bytes.fromhex(sibling)
            else:
                combined = bytes.fromhex(sibling) + bytes.fromhex(current_hash)
            current_hash = sha256_hex(combined)
        return current_hash.lower() == expected_root.lower()
