"""
ChainSync Dashboard & Node API Server (Task T6)
FastAPI backend providing REST and WebSocket APIs for:
- Live semaphore state inspection
- Block explorer with Merkle inclusion proofs
- Transaction submission and block production
- Protected resource inspection and zombie write demo
"""

import sys
import os
import asyncio
import time
from typing import List, Dict, Any, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from core.node import ChainSyncNode
from core.models import Transaction, TransactionType, Event
from core.crypto import KeyPair, MerkleTree
from services.protected_resource import ProtectedResourceService

app = FastAPI(title="ChainSync Node & Block Explorer")

# Initialize global node & protected resource
STORAGE_PATH = "data/chainsync_live.jsonl"
node = ChainSyncNode(node_id="validator-node-1", storage_path=STORAGE_PATH)
protected_resource = ProtectedResourceService()

# Seed default demo data if clean
if len(node.ledger.blocks) <= 1:
    admin_kp = KeyPair.generate()
    # Create sample mutexes
    node.submit_tx(Transaction(type=TransactionType.CREATE, semaphore="db-account-mutex", capacity=1, request_id="seed-1").sign(admin_kp))
    node.submit_tx(Transaction(type=TransactionType.CREATE, semaphore="compute-cluster-sem", capacity=3, request_id="seed-2").sign(admin_kp))
    node.produce_block()
    # Initialize protected resource
    protected_resource.write("account:42", {"owner": "Alice", "balance": 1500}, fencing_token=0, writer_id="GENESIS")

# Active WebSocket connections
active_connections: List[WebSocket] = []


def on_node_event(event: Event):
    # Broadcast to all connected clients
    ev_data = event.model_dump()
    loop = asyncio.get_event_loop()
    if loop.is_running():
        for ws in list(active_connections):
            asyncio.create_task(ws.send_json({"type": "EVENT", "data": ev_data}))


node.subscribe_events(on_node_event)


@app.get("/api/status")
def get_status():
    return {
        "node_id": node.node_id,
        "height": node.ledger.height,
        "latest_block_hash": node.ledger.latest_block.block_hash,
        "latest_block_time": node.ledger.latest_block.header.timestamp,
        "mempool_size": node.mempool.size(),
        "integrity_ok": node.ledger.verify_integrity()[0]
    }


@app.get("/api/semaphores")
def get_semaphores():
    sems = node.get_all_semaphores()
    return {name: snap.model_dump() for name, snap in sems.items()}


@app.get("/api/blocks")
def get_blocks():
    # Return blocks in reverse chronological order
    return [b.model_dump() for b in reversed(node.ledger.blocks)]


@app.get("/api/merkle_proof")
def get_merkle_proof(height: int, tx_hash: str):
    proof = node.ledger.get_merkle_proof(height, tx_hash)
    if proof is None:
        return JSONResponse(status_code=404, content={"error": "Block or transaction not found"})
    return proof


class SubmitTxRequest(BaseModel):
    type: str
    semaphore: str
    capacity: Optional[int] = None
    lease_ms: Optional[int] = None
    token: Optional[int] = None
    request_id: str
    sender_private_hex: Optional[str] = None


@app.post("/api/submit_tx")
def submit_transaction(req: SubmitTxRequest):
    if req.sender_private_hex:
        kp = KeyPair.from_private_hex(req.sender_private_hex)
    else:
        kp = KeyPair.generate()

    tx = Transaction(
        type=TransactionType(req.type),
        semaphore=req.semaphore,
        capacity=req.capacity,
        lease_ms=req.lease_ms,
        token=req.token,
        request_id=req.request_id
    ).sign(kp)

    success, msg = node.submit_tx(tx)
    if not success:
        return JSONResponse(status_code=400, content={"error": msg})

    return {
        "status": "ACCEPTED_INTO_MEMPOOL",
        "tx_hash": tx.tx_hash(),
        "sender": tx.sender,
        "request_id": tx.request_id
    }


@app.post("/api/produce_block")
def produce_block():
    block = node.produce_block()
    return {
        "status": "BLOCK_COMMITTED",
        "height": block.header.height,
        "block_hash": block.block_hash,
        "tx_count": len(block.transactions)
    }


@app.get("/api/protected_resource")
def get_protected_resource():
    return {
        "storage": protected_resource.storage,
        "highest_tokens": protected_resource.highest_tokens,
        "audit_log": protected_resource.get_audit_log()
    }


class FencedWriteRequest(BaseModel):
    key: str
    value: Any
    fencing_token: int
    writer_id: str


@app.post("/api/protected_resource/write")
def protected_write(req: FencedWriteRequest):
    success, msg = protected_resource.write(
        key=req.key,
        value=req.value,
        fencing_token=req.fencing_token,
        writer_id=req.writer_id,
        timestamp_ms=int(time.time() * 1000)
    )
    return {"success": success, "message": msg}


@app.websocket("/ws/events")
async def websocket_events(websocket: WebSocket):
    await websocket.accept()
    active_connections.append(websocket)
    try:
        while True:
            # Keepalive ping
            await websocket.receive_text()
    except WebSocketDisconnect:
        if websocket in active_connections:
            active_connections.remove(websocket)


# Mount static directory for frontend
static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
os.makedirs(static_dir, exist_ok=True)
app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("dashboard.server:app", host="127.0.0.1", port=8000, reload=True)
