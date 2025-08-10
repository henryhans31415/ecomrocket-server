"""Entry point for the eazymode.ai / ecomrocket.ai backend.

This file implements a minimal FastAPI server that demonstrates how to
structure a multi‑tenant, program‑driven coaching platform. It is not
production ready, but provides a scaffold for further development.  It
supports:

* User onboarding and assignment of daily tasks.
* Program and sequence definitions via JSON (see sequences.json).
* Simple completion and blocker flows.
* Upgrade mechanics with placeholder payment integration.
* Multi‑tenant support so multiple brands (e.g., ecomrocket.ai and
  downstream B2B clients via eazymode.ai) can coexist.

The goal is to separate core logic from chat adapters (WhatsApp,
Telegram) so that the same business logic can be reused with any
messaging channel. This server exposes HTTP endpoints that the chat
adapters can call. For real deployments, you would deploy the chat
webhook endpoints on a public URL and secure them with
authentication.

To run this example locally:

```sh
pip install fastapi uvicorn pydantic
python eazymode_server/main.py
```

This will start a development server on http://0.0.0.0:8000 where you
can exercise the API with tools like curl or Postman. For example,
you can onboard a user then fetch their next tasks.

Note: The persistence layer is an in‑memory dictionary. All state
resets when the process restarts. Replace with a real database
(e.g. Postgres or Supabase) for production use.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Data models
#
# These Pydantic models define the structure of sequences, tasks and user
# progress. They are deliberately simple to make it easy to replace the
# in‑memory storage with a proper database. All date fields use ISO 8601
# formatted strings for ease of client integration.


class TaskDefinition(BaseModel):
    """Definition of a single task within a sequence."""

    id: str
    title: str
    instructions: List[str]
    resources: List[str] = Field(default_factory=list)
    xp: int = 10  # XP awarded when completed


class GateDefinition(BaseModel):
    """Definition of a gate (boss check) that must be passed to unlock a
    sequence. A gate can specify automatic checks that the system can
    evaluate or leave them empty so that a human coach evaluates the
    user’s submission. In this scaffold we only implement a manual gate.
    """

    rubric: List[str] = Field(default_factory=list)


class SequenceDefinition(BaseModel):
    """Definition of a sequence within a program."""

    id: str
    title: str
    description: str
    price_usd: float = 0.0  # cost to unlock this sequence
    prereq: Optional[str] = None  # sequence id that must be completed first
    tasks: List[TaskDefinition]
    gate: Optional[GateDefinition] = None


class ProgramDefinition(BaseModel):
    """A program is a set of sequences. Each program belongs to a tenant.
    """

    id: str
    title: str
    description: str
    sequences: List[SequenceDefinition]


class UserProgress(BaseModel):
    """Tracks a user’s progress through a program.

    * `current_sequence_index` identifies which sequence the user is
      currently working on.  It is an index into the program’s
      sequences list.  When equal to len(program.sequences) the user
      has completed the program.
    * `completed_tasks` is a set of task IDs the user has completed.
    * `blocked_tasks` tracks tasks where the user has indicated a
      blocker.  The string value can hold a brief description of the
      blocker, but more context should be collected through the chat
      adapter.
    * `xp` accumulates experience points across tasks.  These can be
      used to unlock sequences or drive gamified features like
      streaks.
    * `mentorship_eligible` is a flag that a coach can set once the
      user meets certain criteria (e.g. program completion + momentum
      threshold). This scaffolds the mentorship tier described in the
      product plan.
    """

    user_id: str
    program_id: str
    current_sequence_index: int = 0
    completed_tasks: Dict[str, datetime] = Field(default_factory=dict)
    blocked_tasks: Dict[str, str] = Field(default_factory=dict)
    xp: int = 0
    mentorship_eligible: bool = False

    # Track which paid sequences the user has unlocked. Keys are sequence
    # IDs and values are booleans indicating purchase status. In the free
    # foundation sequence this map will be empty. The chat adapters can
    # call the purchase endpoint to toggle entries here once a payment
    # succeeds. See `purchase_sequence` below.
    unlocked_sequences: Dict[str, bool] = Field(default_factory=dict)


class Tenant(BaseModel):
    """A tenant represents a customer of the platform (e.g. ecomrocket.ai for
    the DTC use case or a B2B client using eazymode.ai). Each tenant has
    its own programs and users. In a real system you would also
    include branding information and contact details here.
    """

    id: str
    name: str
    programs: Dict[str, ProgramDefinition] = Field(default_factory=dict)
    users: Dict[str, UserProgress] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# In‑memory “database”
#
# For demonstration purposes we store tenants, programs, sequences and
# progress in Python dictionaries. In production you would replace
# these with calls to a persistent datastore such as Postgres or
# Firestore. Because this is in‑memory, all data resets whenever the
# server restarts.

TENANTS: Dict[str, Tenant] = {}


# ---------------------------------------------------------------------------
# Utility functions

def load_programs_from_file(path: Path) -> List[ProgramDefinition]:
    """Load program definitions from a JSON file. The file format should be
    a list of program objects conforming to ProgramDefinition. This
    function is used during startup to seed example programs.
    """

    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return [ProgramDefinition(**p) for p in data]


def create_tenant(name: str, programs: List[ProgramDefinition]) -> Tenant:
    """Create a new tenant with the provided programs. A unique tenant ID is
    generated using UUID4. The programs are stored in a map keyed by
    program id for O(1) lookup. When a new tenant is created it has no
    users.
    """

    tenant_id = str(uuid.uuid4())
    program_map = {p.id: p for p in programs}
    tenant = Tenant(id=tenant_id, name=name, programs=program_map)
    TENANTS[tenant_id] = tenant
    return tenant


def get_tenant(tenant_id: str) -> Tenant:
    if tenant_id not in TENANTS:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return TENANTS[tenant_id]


def get_user_progress(tenant: Tenant, user_id: str) -> UserProgress:
    if user_id not in tenant.users:
        raise HTTPException(status_code=404, detail="User not found")
    return tenant.users[user_id]


# ---------------------------------------------------------------------------
# FastAPI app and endpoints

app = FastAPI(title="Eazymode / Ecomrocket Coaching API")


class OnboardRequest(BaseModel):
    """Request body for onboarding a new user."""
    user_id: str
    program_id: str


class CompleteTaskRequest(BaseModel):
    task_id: str
    proof: Optional[str] = None  # URL or description of proof


class BlockTaskRequest(BaseModel):
    task_id: str
    reason: str


class GateResultRequest(BaseModel):
    sequence_id: str
    passed: bool
    feedback: Optional[str] = None


class PurchaseSequenceRequest(BaseModel):
    """Request body for purchasing a paid sequence.

    The caller should include the ID of the sequence being purchased. In
    a production system this endpoint would verify payment status via a
    webhook from Stripe or Telegram Stars. Here we simply flag the
    sequence as unlocked on the user progress record.
    """

    sequence_id: str


@app.post("/tenant", summary="Create a new tenant")
def create_tenant_endpoint(name: str):
    """Create a tenant. Use this to bootstrap ecomrocket.ai and
    eazymode.ai in your own deployment. Returns the tenant ID which you
    must use for subsequent requests. In a real system this would be
    restricted to admin roles.
    """

    example_programs_path = Path(__file__).parent / "sequences.json"
    programs = load_programs_from_file(example_programs_path)
    tenant = create_tenant(name, programs)
    return {"tenant_id": tenant.id}


@app.post("/tenant/{tenant_id}/onboard", summary="Onboard a user to a program")
def onboard_user(tenant_id: str, req: OnboardRequest):
    tenant = get_tenant(tenant_id)
    if req.program_id not in tenant.programs:
        raise HTTPException(status_code=404, detail="Program not found")
    # If user already exists, return existing progress
    if req.user_id in tenant.users:
        return tenant.users[req.user_id]
    # Create progress record
    progress = UserProgress(user_id=req.user_id, program_id=req.program_id)
    tenant.users[req.user_id] = progress
    return progress


@app.get(
    "/tenant/{tenant_id}/user/{user_id}/next",
    summary="Get the next tasks for a user",
)
def get_next_tasks(tenant_id: str, user_id: str):
    tenant = get_tenant(tenant_id)
    progress = get_user_progress(tenant, user_id)
    program = tenant.programs[progress.program_id]
    if progress.current_sequence_index >= len(program.sequences):
        return {"message": "Program complete", "next_tasks": []}
    sequence = program.sequences[progress.current_sequence_index]
    # If the sequence requires payment and has not been unlocked, do not
    # return any tasks. The chat adapter can surface a paywall message
    # describing the benefits and price. Once purchased via the
    # /purchase endpoint the user can proceed.
    if sequence.price_usd > 0 and not progress.unlocked_sequences.get(sequence.id, False):
        return {
            "sequence": sequence.title,
            "tasks": [],
            "locked": True,
            "price_usd": sequence.price_usd,
            "message": "This sequence requires an upgrade to unlock."
        }
    next_tasks = []
    for task in sequence.tasks:
        if task.id not in progress.completed_tasks and task.id not in progress.blocked_tasks:
            next_tasks.append(task)
    return {
        "sequence": sequence.title,
        "tasks": next_tasks,
    }


@app.post(
    "/tenant/{tenant_id}/user/{user_id}/complete",
    summary="Mark a task as complete and award XP",
)
def complete_task(tenant_id: str, user_id: str, req: CompleteTaskRequest):
    tenant = get_tenant(tenant_id)
    progress = get_user_progress(tenant, user_id)
    program = tenant.programs[progress.program_id]
    if progress.current_sequence_index >= len(program.sequences):
        raise HTTPException(status_code=400, detail="Program already completed")
    sequence = program.sequences[progress.current_sequence_index]
    # Find the task
    task = next((t for t in sequence.tasks if t.id == req.task_id), None)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found in current sequence")
    # Record completion and award XP
    progress.completed_tasks[task.id] = datetime.utcnow()
    progress.xp += task.xp
    # Move to next sequence if all tasks completed and gate passed or no gate
    all_completed = all(
        t.id in progress.completed_tasks for t in sequence.tasks
    )
    if all_completed:
        if sequence.gate is None:
            progress.current_sequence_index += 1
        # Else wait for gate evaluation via /gate endpoint
    return progress


@app.post(
    "/tenant/{tenant_id}/user/{user_id}/block",
    summary="Record a blocker for a task",
)
def block_task(tenant_id: str, user_id: str, req: BlockTaskRequest):
    tenant = get_tenant(tenant_id)
    progress = get_user_progress(tenant, user_id)
    program = tenant.programs[progress.program_id]
    sequence = program.sequences[progress.current_sequence_index]
    if not any(t.id == req.task_id for t in sequence.tasks):
        raise HTTPException(status_code=404, detail="Task not found in current sequence")
    progress.blocked_tasks[req.task_id] = req.reason
    return progress


@app.post(
    "/tenant/{tenant_id}/user/{user_id}/gate",
    summary="Submit result of a gate evaluation",
)
def gate_result(tenant_id: str, user_id: str, req: GateResultRequest):
    tenant = get_tenant(tenant_id)
    progress = get_user_progress(tenant, user_id)
    program = tenant.programs[progress.program_id]
    # Ensure sequence id matches current sequence
    if progress.current_sequence_index >= len(program.sequences):
        raise HTTPException(status_code=400, detail="Program already completed")
    sequence = program.sequences[progress.current_sequence_index]
    if sequence.id != req.sequence_id:
        raise HTTPException(status_code=400, detail="Not at this gate yet")
    if req.passed:
        progress.current_sequence_index += 1
    # else: remain in sequence; coach may prescribe remedial work
    return progress


# ---------------------------------------------------------------------------
# Additional endpoints for purchases, mentorship and admin views

@app.post(
    "/tenant/{tenant_id}/user/{user_id}/purchase",
    summary="Mark a paid sequence as purchased",
)
def purchase_sequence(tenant_id: str, user_id: str, req: PurchaseSequenceRequest):
    """
    Flag a sequence as unlocked for a given user. This endpoint is called by
    the chat adapter after a successful payment. The sequence ID must
    correspond to one of the program's sequences. Once unlocked, the user
    can progress into that sequence when prerequisites are met. Purchases
    do not advance the current sequence automatically; users must still
    complete tasks or pass gates.
    """
    tenant = get_tenant(tenant_id)
    progress = get_user_progress(tenant, user_id)
    program = tenant.programs[progress.program_id]
    if not any(seq.id == req.sequence_id for seq in program.sequences):
        raise HTTPException(status_code=404, detail="Sequence not found in program")
    progress.unlocked_sequences[req.sequence_id] = True
    return {"unlocked_sequences": progress.unlocked_sequences}


@app.post(
    "/tenant/{tenant_id}/user/{user_id}/mentorship/apply",
    summary="Apply for mentorship eligibility",
)
def apply_for_mentorship(tenant_id: str, user_id: str):
    """
    Mark a user as eligible for the high‑touch mentorship tier. In a real
    system you would evaluate user progress, XP and other metrics before
    flipping this flag. Here we simply set it to True and return the
    updated progress record.
    """
    tenant = get_tenant(tenant_id)
    progress = get_user_progress(tenant, user_id)
    progress.mentorship_eligible = True
    return progress


@app.get(
    "/tenant/{tenant_id}/users",
    summary="List all users and their progress for a tenant",
)
def list_users(tenant_id: str):
    """
    Return all user progress records for a tenant. This is useful for
    building the owner dashboard or retrieving aggregated metrics. In
    production you would restrict this endpoint to authenticated owners.
    """
    tenant = get_tenant(tenant_id)
    return list(tenant.users.values())


@app.get(
    "/tenant/{tenant_id}/user/{user_id}/progress",
    summary="Get full progress report for a user",
)
def get_progress(tenant_id: str, user_id: str):
    tenant = get_tenant(tenant_id)
    progress = get_user_progress(tenant, user_id)
    return progress


@app.get(
    "/health",
    summary="Health check endpoint",
)
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)