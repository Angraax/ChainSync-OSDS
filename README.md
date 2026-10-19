# ChainSync: Blockchain-Based Process Synchronization

> **Replacing Semaphores with Blockchain Consensus & State Machine Replication (SMR)**  
> Team: **Tijay** (Ledger, Lock Logic & Visibility) & **Ujjwal** (Consensus, Network & Performance)

---

## 🏛️ Architecture Overview

In ChainSync, distributed mutual exclusion and process synchronization are achieved without a single trusted server:
1. **Replicated State Machine (`apply(tx, block_time)`):** A deterministic, pure lock manager state machine where same state + same transaction + agreed block time = same new state on every node.
2. **Blockchain Consensus Log:** Consensus engine (Raft / PBFT) guarantees every node receives transactions in the exact same total order.
3. **Monotonic Fencing Tokens:** Every grant increments a monotonic token ($1, 2, 3\dots$) that protected storage services inspect to strictly reject zombie writes from expired holders.
4. **Block-Time Lease Expiry:** Node clocks never interleave; leases expire strictly via deterministic block timestamps advanced by leader `TICK` blocks.

---

## 📂 Project Directory Structure

```text
d:/ChainSync OSDS CP/
├── proto/
│   └── chainsync.proto         # Shared proto contract frozen for both halves
├── core/
│   ├── crypto.py               # Ed25519 signing & Merkle tree inclusion proofs
│   ├── models.py               # Core data models for Tx, Block, Event, Semaphore
│   ├── lock_manager.py         # Task T1: Pure deterministic Lock Manager State Machine
│   ├── ledger.py               # Task T2: Append-only hash chain, Merkle root & tamper detection
│   ├── mempool.py              # Task T3: Deduplicating mempool & TICK block generator
│   └── node.py                 # Unified ChainSync Node orchestrator
├── services/
│   └── protected_resource.py   # Task T5: Protected resource enforcing fencing tokens
├── tests/
│   ├── test_lock_manager.py    # Unit tests for Task T1
│   ├── test_property_invariants.py # Task T4: Invariant property tests (Mutual Exclusion, FIFO, Monotonicity)
│   ├── test_ledger_and_fencing.py # Task T2 & T5: Merkle verification, tamper detection, zombie write blocks
│   └── test_conformance.py     # Task T8: Shared client-level conformance test suite
├── demos/
│   ├── dining_philosophers.py  # Task T7: 5 Philosophers concurrency demo
│   ├── bank_transfer.py        # Task T7: Financial transfer with zombie write defense
│   └── producer_consumer.py    # Task T7: Bounded buffer counting semaphores
├── dashboard/                  # Task T6: Interactive Web UI & Block Explorer
│   ├── server.py               # FastAPI + WebSocket backend
│   └── static/
│       ├── index.html          # Modern glassmorphism dashboard
│       ├── style.css           # Sleek dark theme stylesheet
│       └── app.js              # Real-time state ticker, Merkle verifier & actions
├── data/                       # Append-only blockchain storage & demo data
└── README.md
```

---

## 🚀 Running the Project

### 1. Run All Tests (13/13 Invariant & Conformance Tests)
```powershell
python -m pytest tests/ -v
```

### 2. Run Classic Concurrency Demos (Task T7)
- **Dining Philosophers:**
  ```powershell
  python demos/dining_philosophers.py
  ```
- **Bank Account Transfer & Zombie Defense:**
  ```powershell
  python demos/bank_transfer.py
  ```
- **Producer-Consumer Bounded Buffer:**
  ```powershell
  python demos/producer_consumer.py
  ```

### 3. Launch the Interactive Dashboard & Block Explorer (Task T6)
```powershell
python -m uvicorn dashboard.server:app --reload --port 8000
```
Open your browser to: **`http://127.0.0.1:8000`** to visualize:
- Live semaphores, active holders with countdown progress bars, and waiting queues.
- Interactive Transaction Dispatcher (`ACQUIRE`, `RELEASE`, `RENEW`, `CREATE`).
- Blockchain Explorer with expandable block details and Merkle roots.
- Interactive Cryptographic Merkle Inclusion Proof Verifier.
- Protected Storage & Zombie Write Simulation panel.
