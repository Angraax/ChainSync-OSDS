"""
ChainSync Protected Resource Service (Task T5)
Demonstrates fencing token verification to prevent zombie writes and split-brain corruptions.
As detailed in Chapter 6 & Chapter 17:
A process paused by a GC stall, network delay, or OS sleep may wake up AFTER its lease expired.
By checking monotonically increasing fencing tokens, the protected storage service strictly
rejects stale requests from zombie clients.
"""

from typing import Dict, Any, Tuple, List, Optional
from pydantic import BaseModel


class WriteRecord(BaseModel):
    key: str
    value: Any
    fencing_token: int
    writer_id: str
    status: str       # "ACCEPTED" or "REJECTED_STALE_TOKEN"
    timestamp_ms: int


class ProtectedResourceService:
    def __init__(self):
        # Key -> Value
        self.storage: Dict[str, Any] = {}
        # Key -> Highest fencing token accepted
        self.highest_tokens: Dict[str, int] = {}
        # Audit history of all write attempts
        self.audit_log: List[WriteRecord] = []

    def write(self, key: str, value: Any, fencing_token: int, writer_id: str, timestamp_ms: int = 0) -> Tuple[bool, str]:
        """
        Executes a fenced write on the protected resource.
        Rejects any request whose fencing_token < highest_tokens[key].
        """
        highest = self.highest_tokens.get(key, 0)

        if fencing_token < highest:
            # Stale zombie write detected!
            record = WriteRecord(
                key=key,
                value=value,
                fencing_token=fencing_token,
                writer_id=writer_id,
                status="REJECTED_STALE_TOKEN",
                timestamp_ms=timestamp_ms
            )
            self.audit_log.append(record)
            return False, f"REJECTED: Stale fencing token {fencing_token} < highest seen {highest} (Zombie write prevented)"

        # Valid monotonic fencing token
        self.storage[key] = value
        self.highest_tokens[key] = fencing_token
        record = WriteRecord(
            key=key,
            value=value,
            fencing_token=fencing_token,
            writer_id=writer_id,
            status="ACCEPTED",
            timestamp_ms=timestamp_ms
        )
        self.audit_log.append(record)
        return True, f"ACCEPTED: Updated key '{key}' with fencing token {fencing_token}"

    def read(self, key: str) -> Tuple[Optional[Any], int]:
        """Returns (value, current_highest_token)."""
        return self.storage.get(key), self.highest_tokens.get(key, 0)

    def get_audit_log(self) -> List[Dict[str, Any]]:
        return [r.model_dump() for r in self.audit_log]
