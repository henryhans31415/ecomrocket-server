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
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import os
from supabase import create_client, Client
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

    # --- Gamification fields ---
    # The current level of the user based on accumulated XP. Level 1
    # corresponds to zero XP. Higher levels unlock cosmetic badges
    # or additional community rings in the client UI. The level is
    # recomputed whenever XP changes.
    level: int = 1

    # Timestamp of the last task completion. Used to compute streaks.
    last_task_completion: Optional[datetime] = None

    # Number of consecutive days the user has completed at least one task.
    streak_days: int = 0

    # A list of badge identifiers the user has earned. Badges are
    # awarded by the coach or automatically by hitting milestones.
    badges: List[str] = Field(default_factory=list)


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
    # A mapping of brand_id to BrandData. A tenant may manage multiple
    # brands (e.g. Quiet Body, Essencraft). Each brand has its own set
    # of phases and tasks which feed the PhaseGlass and schedule views.
    brands: Dict[str, "BrandData"] = Field(default_factory=dict)


class PhaseTaskData(BaseModel):
    """Represents a single task within a phase for the brand dashboard.

    Each task belongs to a phase and may depend on other tasks across
    phases. A duration (in days) can be specified to allow schedule
    computations. The status field tracks whether the task is still
    pending (`"todo"`), in progress, or completed (`"done"`).
    """
    id: str
    name: str
    description: Optional[str] = None
    duration_days: Optional[int] = None
    weight: int = 1
    status: str = "todo"
    depends_on: List[str] = Field(default_factory=list)


class PhaseData(BaseModel):
    """A collection of tasks grouped under a phase (e.g. Company Setup).

    The key field is a short identifier (e.g. `company_setup`) used in
    dependency definitions. Order determines the display order in the
    PhaseGlass. Weight allows some phases to contribute more to the
    overall launch readiness than others.
    """
    id: str
    key: str
    name: str
    order: int
    weight: int = 1
    tasks: Dict[str, PhaseTaskData] = Field(default_factory=dict)


class BrandData(BaseModel):
    """A brand represents a product/business launch under a tenant.

    Brands allow the owner to manage multiple launches in parallel.
    Each brand has phases and tasks that roll up into completion
    metrics and schedules. A color token and logo URL can be stored
    here for client customization.
    """
    id: str
    name: str
    color_token: Optional[str] = None
    logo_url: Optional[str] = None
    phases: Dict[str, PhaseData] = Field(default_factory=dict)

    # A simple mapping of SKU → stock snapshot for the StockVials
    # feature. Each entry holds on_hand, inbound and days_cover
    # values. This in‑memory structure drives the StockVials gauges in
    # the dashboard. Persistent snapshots are written to the
    # ``inventory_snapshots`` table when Supabase is configured.
    stock_vials: Dict[str, Dict[str, Optional[int]]] = Field(default_factory=dict)

    # A collection of assets (files or embeds) associated with the
    # brand. Keys are asset IDs and values store metadata such as
    # phase_id, url, type and tags. These are used to power the
    # Design Board. Persistent copies are written to the ``assets``
    # table when Supabase is configured.
    assets: Dict[str, Dict] = Field(default_factory=dict)
    # A list of event objects for this brand. Each event captures a
    # significant change (e.g. task completed, blocker recorded,
    # schedule shift) along with a timestamp. In-memory events will
    # reset on restart; to persist them set SUPABASE_URL and
    # SUPABASE_ANON_KEY so that events are inserted into the
    # ``events`` table in Supabase. See ``log_event`` helper below.
    events: List[Dict] = Field(default_factory=list)


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
# Supabase initialization
#
# To persist user progress across restarts, we optionally write progress
# records to a Supabase table named `user_progress`. The table schema is
# defined in schema.sql. If the SUPABASE_URL and SUPABASE_ANON_KEY
# environment variables are set, the server will initialize a Supabase
# client and write progress updates to the database. Otherwise, all
# persistence remains in memory. This allows the same codebase to run
# locally without external dependencies while enabling cloud persistence
# when deployed.

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")
supabase: Optional[Client] = None
if SUPABASE_URL and SUPABASE_ANON_KEY:
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
    except Exception:
        # If Supabase initialization fails, continue without persistence
        supabase = None


def sync_progress_to_db(progress: UserProgress, tenant_id: str) -> None:
    """Persist a user's progress to the Supabase database.

    This helper will upsert the progress row into the `user_progress`
    table. It gracefully handles the case where Supabase is not
    configured by doing nothing. The table schema must match the
    dictionary keys below. If the upsert fails, the exception is
    swallowed because persistence is best effort in this scaffold.

    Parameters
    ----------
    progress: UserProgress
        The progress object to persist.
    tenant_id: str
        The tenant identifier for multi‑tenant separation.
    """
    if not supabase:
        return
    # Prepare the row data. We flatten nested structures into JSON
    # compatible types. datetime objects are converted to ISO strings.
    row = {
        "tenant_id": tenant_id,
        "user_id": progress.user_id,
        "program_id": progress.program_id,
        "current_sequence_index": progress.current_sequence_index,
        "current_task_index": len(progress.completed_tasks),
        "xp": progress.xp,
        "level": progress.level,
        "streak_days": progress.streak_days,
        "last_completed_at": progress.last_task_completion.isoformat() if progress.last_task_completion else None,
        "badges": progress.badges,
        "unlocked_sequences": progress.unlocked_sequences,
        "mentorship_eligible": progress.mentorship_eligible,
    }
    try:
        supabase.table("user_progress").upsert(row, on_conflict="user_id").execute()
    except Exception:
        # Ignore persistence errors in this scaffold
        pass

# ---------------------------------------------------------------------------
# Brand/Phase/Task helpers and schedule computation

def create_brand(tenant: Tenant, name: str, color_token: Optional[str] = None, logo_url: Optional[str] = None) -> BrandData:
    """
    Create a new brand within a tenant. Generates a UUID for the brand.
    """
    brand_id = str(uuid.uuid4())
    brand = BrandData(id=brand_id, name=name, color_token=color_token, logo_url=logo_url)
    tenant.brands[brand_id] = brand
    return brand


def create_phase(tenant: Tenant, brand_id: str, key: str, name: str, order: int, weight: int = 1) -> PhaseData:
    """
    Create a new phase within a brand. Phase keys must be unique per brand.
    """
    brand = tenant.brands.get(brand_id)
    if not brand:
        raise HTTPException(status_code=404, detail="Brand not found")
    # Ensure unique key
    if any(p.key == key for p in brand.phases.values()):
        raise HTTPException(status_code=400, detail="Phase key already exists for this brand")
    phase_id = str(uuid.uuid4())
    phase = PhaseData(id=phase_id, key=key, name=name, order=order, weight=weight)
    brand.phases[phase_id] = phase
    return phase


def create_phase_task(
    tenant: Tenant,
    brand_id: str,
    phase_id: str,
    name: str,
    description: Optional[str] = None,
    duration_days: Optional[int] = None,
    weight: int = 1,
    depends_on: Optional[List[str]] = None,
) -> PhaseTaskData:
    """
    Create a new task within a phase. Task names must be unique within the phase.
    """
    brand = tenant.brands.get(brand_id)
    if not brand:
        raise HTTPException(status_code=404, detail="Brand not found")
    phase = brand.phases.get(phase_id)
    if not phase:
        raise HTTPException(status_code=404, detail="Phase not found")
    if any(t.name == name for t in phase.tasks.values()):
        raise HTTPException(status_code=400, detail="Task name already exists in this phase")
    task_id = str(uuid.uuid4())
    task = PhaseTaskData(
        id=task_id,
        name=name,
        description=description,
        duration_days=duration_days,
        weight=weight,
        status="todo",
        depends_on=depends_on or [],
    )
    phase.tasks[task_id] = task
    return task


def calculate_phase_progress(phase: PhaseData) -> float:
    """
    Compute the completion percentage for a phase based on task weights.
    Returns a float between 0 and 1. If the phase has no tasks, returns 0.
    """
    if not phase.tasks:
        return 0.0
    total_weight = sum(t.weight for t in phase.tasks.values())
    completed_weight = sum(t.weight for t in phase.tasks.values() if t.status == "done")
    return completed_weight / total_weight if total_weight > 0 else 0.0


def get_phaseglass_for_brand(tenant: Tenant, brand_id: str):
    """
    Compute PhaseGlass metrics for each phase in the brand.
    Returns a list of dicts with phase details, completion percentage, and blockers.
    A blocker is reported when a task has unmet dependencies.
    """
    brand = tenant.brands.get(brand_id)
    if not brand:
        raise HTTPException(status_code=404, detail="Brand not found")
    phaseglass = []
    for phase in sorted(brand.phases.values(), key=lambda p: p.order):
        # Determine blockers: tasks with dependencies not completed
        blockers = []
        for task in phase.tasks.values():
            # If any dependency is not done, and this task is not done, it's a blocker
            if task.status != "done":
                unmet = False
                for dep in task.depends_on:
                    # Look up dependency across all phases of the brand
                    # If dependency not found or not done, it's unmet
                    found = False
                    for p in brand.phases.values():
                        if dep in p.tasks:
                            found = True
                            if p.tasks[dep].status != "done":
                                unmet = True
                            break
                    if not found:
                        unmet = True
                    if unmet:
                        blockers.append({"task_id": task.id, "task_name": task.name, "dependency": dep})
                        break
        completion = calculate_phase_progress(phase)
        phaseglass.append({
            "phase_id": phase.id,
            "key": phase.key,
            "name": phase.name,
            "order": phase.order,
            "weight": phase.weight,
            "completion": completion,
            "blockers": blockers,
        })
    return phaseglass


def calculate_schedule_for_brand(tenant: Tenant, brand_id: str):
    """
    Calculate a simple schedule for the brand using task durations and dependencies.
    Returns an ETA object with total days, a confidence band (±20%), and critical path tasks.
    A completed task (status == 'done') has zero remaining duration.
    """
    brand = tenant.brands.get(brand_id)
    if not brand:
        raise HTTPException(status_code=404, detail="Brand not found")
    # Build a mapping of task_id to task object and adjacency for dependencies
    tasks = {}
    for phase in brand.phases.values():
        for task in phase.tasks.values():
            tasks[task.id] = task
    # Compute earliest start/finish times using DFS (topological order). We assume no cycles.
    start_times = {tid: 0 for tid in tasks.keys()}
    finish_times = {tid: 0 for tid in tasks.keys()}
    # We'll compute finish times by dynamic programming.
    # Define a recursive function to compute finish time for task.
    def compute_finish(tid: str):
        task = tasks[tid]
        # Completed tasks contribute zero time
        duration = task.duration_days or 0
        if task.status == "done":
            duration = 0
        if finish_times[tid] > 0:
            # already computed (memoization)
            return finish_times[tid]
        if not task.depends_on:
            start_times[tid] = 0
            finish_times[tid] = duration
            return finish_times[tid]
        # compute start as max finish of deps
        max_finish = 0
        for dep in task.depends_on:
            if dep in tasks:
                dep_finish = compute_finish(dep)
                if dep_finish > max_finish:
                    max_finish = dep_finish
            else:
                # unknown dep, treat as zero (or could block schedule)
                pass
        start_times[tid] = max_finish
        finish_times[tid] = max_finish + duration
        return finish_times[tid]
    # Compute for all tasks
    for tid in tasks.keys():
        compute_finish(tid)
    # Total schedule is max finish time of all tasks not done
    total_days = max(finish_times.values()) if finish_times else 0
    # Determine critical path tasks: tasks whose finish time equals total_days
    critical_tasks = []
    for tid, finish in finish_times.items():
        if finish == total_days and tasks[tid].status != "done":
            critical_tasks.append({"task_id": tid, "task_name": tasks[tid].name})
    # Confidence band ±20%
    confidence = int(max(total_days * 0.2, 1)) if total_days > 0 else 0
    return {
        "total_days": total_days,
        "eta": f"{total_days}d ± {confidence}d",  # e.g. "90d ± 18d"
        "critical_tasks": critical_tasks,
    }

# ---------------------------------------------------------------------------
# Event logging helper

def log_event(tenant_id: str, brand: BrandData, event_type: str, payload: Dict) -> None:
    """Record an event for a brand and persist it to Supabase if configured.

    Events power the "Today’s pulse" feature in the dashboard. Each event
    captures a timestamp and an arbitrary payload. In memory events are
    appended to ``brand.events``; when Supabase is configured they are
    inserted into the ``events`` table. Errors from Supabase are
    swallowed because persistence is best effort in this scaffold.

    Parameters
    ----------
    tenant_id : str
        The tenant identifier.
    brand : BrandData
        The brand that the event relates to.
    event_type : str
        A short string describing the type of event, e.g. ``"task_completed"``.
    payload : Dict
        Additional details about the event. Should be JSON serializable.
    """
    event = {
        "id": str(uuid.uuid4()),
        "tenant_id": tenant_id,
        "brand_id": brand.id,
        "type": event_type,
        "payload": payload,
        "created_at": datetime.utcnow().isoformat(),
    }
    # Append to in-memory list
    brand.events.append(event)
    # Persist to Supabase if available
    if supabase:
        try:
            supabase.table("events").insert(event).execute()
        except Exception:
            pass


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
# Gamification helpers

def calculate_level(xp: int) -> int:
    """
    Compute the user's level based on accumulated XP. This simple
    implementation uses fixed thresholds: every 100 XP yields a new
    level. Level 1 corresponds to 0–99 XP, level 2 to 100–199 XP, and
    so on. Adjust the thresholds to tune progression speed. In a
    production system you might load these thresholds from a config or
    database to allow dynamic tuning.

    Args:
        xp: The total experience points the user has accumulated.

    Returns:
        The current level as an integer.
    """
    if xp < 0:
        return 1
    return 1 + xp // 100


# ---------------------------------------------------------------------------
# FastAPI app and endpoints

app = FastAPI(title="Eazymode / Ecomrocket Coaching API")

# -----------------------------------------------------------------------
# Cross‑origin resource sharing (CORS) configuration and static dashboard
#
# To support a separate browser‑based dashboard (or any web client) that
# consumes this API from a different domain, we enable permissive CORS.
# In production you should restrict the allowed origins to your own domains
# (e.g., https://ecomrocket.ai and https://eazymode.ai) to prevent abuse.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static files for a basic dashboard.  Files placed in the
# ``eazymode_server/frontend`` directory will be accessible under
# ``/dashboard``.  For example, ``frontend/index.html`` becomes
# ``/dashboard/index.html`` and is also served as the default document at
# ``/dashboard/`` when the ``html=True`` flag is set.  This allows you to
# include a lightweight HTML/JS dashboard within the same service without
# deploying a separate static site.  The dashboard can call the API using
# relative URLs (since CORS permits it).
app.mount(
    "/dashboard",
    StaticFiles(directory=os.path.join(os.path.dirname(__file__), "frontend"), html=True),
    name="dashboard",
)

@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def root():
    """Serve a basic landing page at the service root.

    When a user navigates to the root domain (e.g. https://ecomrocket.ai/ or
    https://eazymode.ai/) this handler returns a small HTML page with a
    welcome message and a link to the API docs.  Without this handler the
    backend would respond with a 404 error for the root path.

    Returns:
        HTML containing a welcome header and a link to the API docs.
    """
    return """
    <!DOCTYPE html>
    <html lang="en">
      <head>
        <meta charset="utf-8" />
        <title>Eazymode / Ecomrocket Coaching API</title>
        <style>
          body { font-family: sans-serif; margin: 2rem; line-height: 1.6; }
          h1 { color: #333; }
          a { color: #0055a5; text-decoration: none; }
          a:hover { text-decoration: underline; }
        </style>
      </head>
      <body>
        <h1>Welcome to the Eazymode / Ecomrocket Coaching API</h1>
        <p>
          This service powers the coaching programs offered by
          <strong>ecomrocket.ai</strong> and our white‑label
          platform <strong>eazymode.ai</strong>.
        </p>
        <p>
          To explore the available endpoints and try them out interactively,
          visit the <a href="/docs">API documentation</a>.
        </p>
      </body>
    </html>
    """


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


class AwardBadgeRequest(BaseModel):
    """
    Request body for awarding a badge to a user. A badge is a
    string identifier that will be appended to the user's list of
    badges. In a gamified program you might define badges such as
    "product_hunter", "supplier_whisperer" or use custom names. The
    chat adapter can call this endpoint when the coach manually awards
    a badge or when an automated milestone is reached.
    """
    badge: str

# ---------------------------------------------------------------------------
# Inventory and asset request models

class StockSnapshotRequest(BaseModel):
    """Request payload for updating a stock snapshot.

    Each snapshot specifies the SKU, units on hand, inbound purchase
    order quantity and optionally a days of cover estimate. The
    endpoint updates the in‑memory StockVials for the brand and
    persists a record to the ``inventory_snapshots`` table when
    Supabase is configured. The "days_cover" field indicates how many
    days the on_hand inventory will last at current burn; it can be
    omitted.
    """
    sku: str
    on_hand: int
    inbound: int
    days_cover: Optional[int] = None


class AssetCreateRequest(BaseModel):
    """Request payload for creating a design/ops asset.

    Assets include images, PDFs, videos or external embeds. Each
    asset belongs to a brand and may optionally be tied to a phase.
    The ``url`` field should point to a publicly accessible location
    (e.g. Supabase Storage or Figma). ``type`` is a short string
    describing the file type (e.g. "image", "pdf", "video",
    "figma"). Tags can be used to categorise assets and support
    filtering on the front‑end.
    """
    phase_id: Optional[str] = None
    url: str
    type: str
    tags: List[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# What-if and chat ingestion request models

class WhatIfModification(BaseModel):
    """Represents a hypothetical change to a task's duration.

    The ``task_id`` references a PhaseTaskData within a brand. The
    ``duration_days`` field is the temporary duration to apply for
    schedule computation. Use this model in the WhatIfRequest below.
    """
    task_id: str
    duration_days: int


class WhatIfRequest(BaseModel):
    """Request payload for computing a what‑if schedule.

    Provide a list of modifications to override task durations. The
    endpoint will compute a new schedule using the modified durations
    and return the resulting ETA and critical path. This does not
    persist any changes; it is for interactive forecasting.
    """
    modifications: List[WhatIfModification]


class ChatIngestRequest(BaseModel):
    """Request payload for chat ingestion.

    The assistant can call this endpoint with a free‑form message to
    perform updates on brand tasks. The message can include simple
    commands like ``delay <task_id> to <days>``. Only a few patterns
    are supported in this scaffold. Extend the parser as needed.
    """
    brand_id: str
    message: str


# ---------------------------------------------------------------------------
# Brand and phase creation request models

class BrandCreateRequest(BaseModel):
    """Request payload for creating a new brand.

    A brand encapsulates a single product or business launch. The
    optional `color_token` and `logo_url` fields allow the front‑end
    application to theme the dashboard per brand.
    """
    name: str
    color_token: Optional[str] = None
    logo_url: Optional[str] = None


class PhaseCreateRequest(BaseModel):
    """Request payload for creating a new phase within a brand."""
    key: str
    name: str
    order: int
    weight: int = 1


class PhaseTaskCreateRequest(BaseModel):
    """Request payload for creating a task within a phase."""
    name: str
    description: Optional[str] = None
    duration_days: Optional[int] = None
    weight: int = 1
    depends_on: List[str] = Field(default_factory=list)


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
    # Persist progress to Supabase if configured
    sync_progress_to_db(progress, tenant_id)
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
    # Update streak and last_task_completion. A streak increases
    # when the user completes at least one task per day without breaks.
    now = datetime.utcnow()
    # Determine if this is the first completion or part of an existing streak
    if progress.last_task_completion is None:
        progress.streak_days = 1
    else:
        # Compute difference in days between the last completion and now
        last_date = progress.last_task_completion.date()
        current_date = now.date()
        delta_days = (current_date - last_date).days
        if delta_days == 0:
            # Completed multiple tasks on the same day; streak unchanged
            pass
        elif delta_days == 1:
            # Consecutive day
            progress.streak_days += 1
        else:
            # Gap detected; reset streak
            progress.streak_days = 1
    # Update last_task_completion timestamp
    progress.last_task_completion = now
    # Recalculate level based on new XP
    progress.level = calculate_level(progress.xp)
    # Move to next sequence if all tasks completed and gate passed or no gate
    all_completed = all(
        t.id in progress.completed_tasks for t in sequence.tasks
    )
    if all_completed:
        if sequence.gate is None:
            progress.current_sequence_index += 1
        # Else wait for gate evaluation via /gate endpoint
    # Update the in‑memory store with the latest progress
    tenant.users[user_id] = progress
    # Persist progress to Supabase if configured
    sync_progress_to_db(progress, tenant_id)
    # Log task completion event on the brand if we can resolve brand
    # Determine the brand associated with the current program and sequence
    # There is no direct mapping in this scaffold; events are not logged for
    # program tasks by default. You can extend this to map sequences to brands.
    return {
        "message": f"Task '{task.title}' completed",
        "xp": progress.xp,
        "level": progress.level,
        "streak": progress.streak_days,
    }


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


# ---------------------------------------------------------------------------
# Gamification and stats endpoints

@app.get(
    "/tenant/{tenant_id}/user/{user_id}/stats",
    summary="Get gamification stats for a user",
)
def get_stats(tenant_id: str, user_id: str):
    """
    Return the gamification statistics for a user. This includes
    experience points, level, streak days and earned badges. Use this
    endpoint to display progress bars, streak counters or badge
    collections in your client UI.
    """
    tenant = get_tenant(tenant_id)
    progress = get_user_progress(tenant, user_id)
    return {
        "xp": progress.xp,
        "level": progress.level,
        "streak_days": progress.streak_days,
        "badges": progress.badges,
    }


@app.post(
    "/tenant/{tenant_id}/user/{user_id}/badge",
    summary="Award a badge to a user",
)
def award_badge(tenant_id: str, user_id: str, req: AwardBadgeRequest):
    """
    Append a badge identifier to the user's list of badges. Duplicate
    badges are ignored. In a real system you might want to validate
    that the badge exists in a catalog of known badges or enforce
    badge awarding rules (e.g. cannot earn the same badge twice).
    """
    tenant = get_tenant(tenant_id)
    progress = get_user_progress(tenant, user_id)
    if req.badge not in progress.badges:
        progress.badges.append(req.badge)
    return {
        "badges": progress.badges,
    }


@app.get(
    "/health",
    summary="Health check endpoint",
)
def health():
    return {"status": "ok"}

# ---------------------------------------------------------------------------
# Program and sequence management endpoints

@app.get(
    "/tenant/{tenant_id}/programs",
    summary="List all programs for a tenant",
)
def list_programs(tenant_id: str):
    """
    Return the program definitions for a tenant. Each program includes
    its sequences and tasks. This endpoint is useful for the B2B
    dashboard to allow owners to view and manage their program
    structure.
    """
    tenant = get_tenant(tenant_id)
    return list(tenant.programs.values())


@app.post(
    "/tenant/{tenant_id}/program",
    summary="Create a new program for a tenant",
)
def create_program(tenant_id: str, program: ProgramDefinition):
    """
    Add a new program to the tenant. The request body must include a
    complete ProgramDefinition with at least one sequence. Program IDs
    must be unique within the tenant. In production you would validate
    that the caller has permission to modify programs. When a program
    is created it is immediately available for onboarding new users.
    """
    tenant = get_tenant(tenant_id)
    if program.id in tenant.programs:
        raise HTTPException(status_code=400, detail="Program ID already exists")
    tenant.programs[program.id] = program
    return program


@app.post(
    "/tenant/{tenant_id}/program/{program_id}/sequence",
    summary="Add a new sequence to an existing program",
)
def add_sequence(tenant_id: str, program_id: str, sequence: SequenceDefinition):
    """
    Append a sequence to an existing program. Sequences are ordered in
    the order they are added. The request body should provide a
    SequenceDefinition with tasks and optional gate. Sequence IDs must
    be unique within the program. If you need to insert a sequence in
    the middle, you can extend this handler to accept an index.
    """
    tenant = get_tenant(tenant_id)
    if program_id not in tenant.programs:
        raise HTTPException(status_code=404, detail="Program not found")
    program = tenant.programs[program_id]
    # Ensure uniqueness of sequence id
    if any(seq.id == sequence.id for seq in program.sequences):
        raise HTTPException(status_code=400, detail="Sequence ID already exists in program")
    program.sequences.append(sequence)
    return sequence


@app.post(
    "/tenant/{tenant_id}/program/{program_id}/sequence/{sequence_id}/task",
    summary="Add a new task to a sequence",
)
def add_task(
    tenant_id: str,
    program_id: str,
    sequence_id: str,
    task: TaskDefinition,
):
    """
    Append a task definition to an existing sequence in a program. Tasks
    within a sequence are executed in the order listed. Task IDs must
    be unique within the sequence. This endpoint enables owners to
    iterate on their curriculum without modifying code.
    """
    tenant = get_tenant(tenant_id)
    if program_id not in tenant.programs:
        raise HTTPException(status_code=404, detail="Program not found")
    program = tenant.programs[program_id]
    sequence = next((seq for seq in program.sequences if seq.id == sequence_id), None)
    if sequence is None:
        raise HTTPException(status_code=404, detail="Sequence not found")
    if any(t.id == task.id for t in sequence.tasks):
        raise HTTPException(status_code=400, detail="Task ID already exists in sequence")
    sequence.tasks.append(task)
    return task


# ---------------------------------------------------------------------------
# Brand/Phase/Task endpoints and phaseglass/schedule endpoints


@app.post(
    "/tenant/{tenant_id}/brand",
    summary="Create a new brand for a tenant",
)
def create_brand_endpoint(tenant_id: str, req: BrandCreateRequest):
    """
    Create a brand under a tenant. The request body must include at
    least a name. A UUID will be generated for the brand. The new
    brand is returned with its generated ID.
    """
    tenant = get_tenant(tenant_id)
    brand = create_brand(tenant, req.name, req.color_token, req.logo_url)
    # Log event for brand creation
    log_event(tenant_id, brand, "brand_created", {"name": req.name})
    return brand


# ---------------------------------------------------------------------------
# Brand listing endpoint

@app.get(
    "/tenant/{tenant_id}/brands",
    summary="List all brands for a tenant",
)
def list_brands_endpoint(tenant_id: str):
    """
    Return a list of all brands created under the specified tenant.  This
    endpoint is useful for the owner and team dashboards to populate a
    portfolio of brands (e.g. Quiet Body, Essencraft, Veluci) for the
    currently logged in tenant.  Each brand includes its ID, name and
    optional color/branding properties.

    Parameters
    ----------
    tenant_id : str
        The identifier of the tenant whose brands should be listed.

    Returns
    -------
    list[BrandData]
        A list of brand objects.
    """
    tenant = get_tenant(tenant_id)
    return list(tenant.brands.values())


@app.post(
    "/tenant/{tenant_id}/brand/{brand_id}/phase",
    summary="Create a new phase within a brand",
)
def create_phase_endpoint(tenant_id: str, brand_id: str, req: PhaseCreateRequest):
    """
    Create a phase within an existing brand. The `key` field must be
    unique within the brand. The `order` field determines the display
    order of phases in the dashboard.
    """
    tenant = get_tenant(tenant_id)
    phase = create_phase(tenant, brand_id, req.key, req.name, req.order, req.weight)
    # Log phase creation event
    brand = tenant.brands.get(brand_id)
    if brand:
        log_event(tenant_id, brand, "phase_created", {"phase_id": phase.id, "key": req.key, "name": req.name})
    return phase


@app.post(
    "/tenant/{tenant_id}/brand/{brand_id}/phase/{phase_id}/task",
    summary="Create a new task within a phase",
)
def create_phase_task_endpoint(
    tenant_id: str,
    brand_id: str,
    phase_id: str,
    req: PhaseTaskCreateRequest,
):
    """
    Append a task to a phase. Task names must be unique within the
    phase. The optional `duration_days` field allows schedule
    computations. Dependencies should reference existing task IDs
    (across any phase in the brand). If a dependency is unknown the
    task is still created but will always remain blocked until the
    dependency is added and completed.
    """
    tenant = get_tenant(tenant_id)
    task = create_phase_task(
        tenant,
        brand_id,
        phase_id,
        req.name,
        req.description,
        req.duration_days,
        req.weight,
        req.depends_on,
    )
    # Log task creation event
    brand = tenant.brands.get(brand_id)
    if brand:
        log_event(tenant_id, brand, "task_created", {
            "phase_id": phase_id,
            "task_id": task.id,
            "name": task.name,
            "duration_days": task.duration_days,
            "depends_on": req.depends_on,
        })
    return task


@app.get(
    "/tenant/{tenant_id}/brand/{brand_id}/phaseglass",
    summary="Get PhaseGlass metrics for a brand",
)
def get_phaseglass_endpoint(tenant_id: str, brand_id: str):
    """
    Compute completion percentages and blockers for each phase in the
    given brand. The response is a list of phase objects containing
    completion (0–1) and blockers. This endpoint powers the PhaseGlass
    view in the owner dashboard.
    """
    tenant = get_tenant(tenant_id)
    return get_phaseglass_for_brand(tenant, brand_id)


@app.get(
    "/tenant/{tenant_id}/brand/{brand_id}/schedule",
    summary="Get schedule and ETA for a brand",
)
def get_schedule_endpoint(tenant_id: str, brand_id: str):
    """
    Calculate the schedule, ETA and critical path tasks for the
    specified brand. The schedule engine uses task durations and
    dependencies to compute an overall time‑to‑launch. Completed tasks
    contribute zero remaining time. The ETA is returned as a string
    with a ±20% confidence band. Critical tasks list the tasks on
    the longest path.
    """
    tenant = get_tenant(tenant_id)
    return calculate_schedule_for_brand(tenant, brand_id)


# ---------------------------------------------------------------------------
# Pulse, what-if and chat ingestion endpoints

@app.get(
    "/tenant/{tenant_id}/brand/{brand_id}/pulse",
    summary="Get recent events (pulse) for a brand",
)
def get_pulse_endpoint(tenant_id: str, brand_id: str, since: Optional[str] = None):
    """
    Return a list of events for the specified brand. Events capture
    significant changes (e.g. task created, phase completed, schedule
    shifts) and are used by the owner dashboard to answer "What
    changed since yesterday?". You can optionally provide a `since`
    query parameter (ISO 8601 timestamp) to filter events created
    after that time. If omitted, only events from the last 24 hours
    are returned.

    Parameters
    ----------
    since : str, optional
        ISO 8601 formatted timestamp. Events created after this time
        will be included. When omitted, events from the last 24 hours
        are returned.
    """
    tenant = get_tenant(tenant_id)
    brand = tenant.brands.get(brand_id)
    if not brand:
        raise HTTPException(status_code=404, detail="Brand not found")
    events = brand.events
    cutoff: Optional[datetime] = None
    if since:
        try:
            cutoff = datetime.fromisoformat(since)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid since timestamp")
    else:
        cutoff = datetime.utcnow() - timedelta(days=1)
    filtered = []
    for e in events:
        try:
            ts = datetime.fromisoformat(e["created_at"])
        except Exception:
            continue
        if cutoff is None or ts > cutoff:
            filtered.append(e)
    return filtered


@app.post(
    "/tenant/{tenant_id}/brand/{brand_id}/whatif",
    summary="Compute a what‑if schedule for a brand",
)
def what_if_endpoint(tenant_id: str, brand_id: str, req: WhatIfRequest):
    """
    Perform a temporary schedule calculation using modified task durations.
    The modifications do not persist; they are applied on a copy of the
    brand data. This allows owners to explore scenarios like "what if
    production slips 7 days" without altering the underlying plan.

    The response mirrors the structure of the ``/schedule`` endpoint.
    """
    tenant = get_tenant(tenant_id)
    brand = tenant.brands.get(brand_id)
    if not brand:
        raise HTTPException(status_code=404, detail="Brand not found")
    # Clone brand and phases for temporary computation
    import copy
    tmp_brand = copy.deepcopy(brand)
    # Apply modifications to temporary tasks
    for mod in req.modifications:
        for p in tmp_brand.phases.values():
            if mod.task_id in p.tasks:
                p.tasks[mod.task_id].duration_days = mod.duration_days
    # Use existing schedule calculator on the cloned brand
    # Build a dummy tenant to satisfy function signature
    tmp_tenant = Tenant(id=tenant.id, name=tenant.name, programs=tenant.programs.copy(), users=tenant.users.copy())
    tmp_tenant.brands = {brand_id: tmp_brand}
    result = calculate_schedule_for_brand(tmp_tenant, brand_id)
    return result


@app.post(
    "/tenant/{tenant_id}/chat/ingest",
    summary="Process a chat message to update brand tasks",
)
def chat_ingest_endpoint(tenant_id: str, req: ChatIngestRequest):
    """
    Parse a free‑form chat message and apply simple updates to brand
    tasks. This scaffold implements a minimal parser that handles
    commands of the form ``delay <task_id> to <days>`` (adjust the
    duration of a task) and ``complete <task_id>`` (mark a brand
    task as done). Unknown commands are ignored. The parsed actions
    update the in‑memory brand and log events. In a production system
    you might integrate a natural language model to parse more
    sophisticated intents and call other endpoints accordingly.
    """
    tenant = get_tenant(tenant_id)
    brand = tenant.brands.get(req.brand_id)
    if not brand:
        raise HTTPException(status_code=404, detail="Brand not found")
    msg = req.message.lower()
    actions = []
    words = msg.split()
    # Simple pattern: delay <task_id> to <days>
    if "delay" in words and "to" in words:
        try:
            idx_delay = words.index("delay")
            idx_to = words.index("to")
            task_id = words[idx_delay + 1]
            days_str = words[idx_to + 1]
            new_duration = int(days_str)
            # Update task duration
            for phase in brand.phases.values():
                if task_id in phase.tasks:
                    phase.tasks[task_id].duration_days = new_duration
                    actions.append({"action": "delay", "task_id": task_id, "duration_days": new_duration})
                    # Log event
                    log_event(tenant_id, brand, "task_duration_changed", {"task_id": task_id, "duration_days": new_duration})
                    break
        except Exception:
            pass
    # Simple pattern: complete <task_id>
    if "complete" in words:
        try:
            idx = words.index("complete")
            task_id = words[idx + 1]
            # Mark task as done
            for phase in brand.phases.values():
                if task_id in phase.tasks:
                    phase.tasks[task_id].status = "done"
                    actions.append({"action": "complete", "task_id": task_id})
                    log_event(tenant_id, brand, "task_completed", {"task_id": task_id})
                    break
        except Exception:
            pass
    return {"applied_actions": actions}

# ---------------------------------------------------------------------------
# Stock and asset endpoints

@app.post(
    "/tenant/{tenant_id}/brand/{brand_id}/stock",
    summary="Update stock snapshot for a SKU",
)
def update_stock_snapshot(tenant_id: str, brand_id: str, req: StockSnapshotRequest):
    """
    Update or insert a stock snapshot for a specific SKU within a brand.

    This endpoint updates the in‑memory stock_vials map on the brand
    and, when Supabase is configured, inserts a new row into the
    ``inventory_snapshots`` table. The snapshot records on_hand and
    inbound units as well as an optional days_of_cover metric. An
    event of type ``stock_updated`` is logged with the payload
    containing the snapshot details. Returns the updated stock entry.
    """
    tenant = get_tenant(tenant_id)
    brand = tenant.brands.get(brand_id)
    if not brand:
        raise HTTPException(status_code=404, detail="Brand not found")
    # Update in‑memory representation
    brand.stock_vials[req.sku] = {
        "sku": req.sku,
        "on_hand": req.on_hand,
        "inbound": req.inbound,
        "days_cover": req.days_cover,
    }
    # Persist snapshot to Supabase
    if supabase:
        row = {
            "tenant_id": tenant_id,
            "brand_id": brand_id,
            "sku": req.sku,
            "on_hand": req.on_hand,
            "inbound": req.inbound,
            "days_cover": req.days_cover,
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
        }
        try:
            supabase.table("inventory_snapshots").insert(row).execute()
        except Exception:
            pass
    # Log event
    log_event(
        tenant_id,
        brand,
        "stock_updated",
        {
            "sku": req.sku,
            "on_hand": req.on_hand,
            "inbound": req.inbound,
            "days_cover": req.days_cover,
        },
    )
    return brand.stock_vials[req.sku]


@app.get(
    "/tenant/{tenant_id}/brand/{brand_id}/stockvials",
    summary="Retrieve stock vials for a brand",
)
def get_stock_vials(tenant_id: str, brand_id: str):
    """
    Return the current stock vials for the specified brand. Each vial
    represents a product SKU with on_hand, inbound and days_cover
    metrics. Use this endpoint to power the StockVials row in the
    owner dashboard. If no stock has been recorded the list will be
    empty.
    """
    tenant = get_tenant(tenant_id)
    brand = tenant.brands.get(brand_id)
    if not brand:
        raise HTTPException(status_code=404, detail="Brand not found")
    return list(brand.stock_vials.values())


@app.post(
    "/tenant/{tenant_id}/brand/{brand_id}/asset",
    summary="Add a design/ops asset to a brand",
)
def add_asset(tenant_id: str, brand_id: str, req: AssetCreateRequest):
    """
    Create a new asset entry for a brand. Assets are files or embeds
    (images, PDFs, videos, Figma frames) that belong to a brand and
    optionally to a phase. The asset is stored in the brand's
    in‑memory ``assets`` map and, when Supabase is configured, is
    persisted to the ``assets`` table. The server logs an event of
    type ``asset_added`` with the asset payload.

    Returns the created asset metadata including the generated asset ID.
    """
    tenant = get_tenant(tenant_id)
    brand = tenant.brands.get(brand_id)
    if not brand:
        raise HTTPException(status_code=404, detail="Brand not found")
    asset_id = str(uuid.uuid4())
    asset = {
        "id": asset_id,
        "phase_id": req.phase_id,
        "url": req.url,
        "type": req.type,
        "tags": req.tags,
    }
    brand.assets[asset_id] = asset
    # Persist to Supabase
    if supabase:
        row = {
            "tenant_id": tenant_id,
            "brand_id": brand_id,
            "phase_id": req.phase_id,
            "url": req.url,
            "type": req.type,
            "tags": req.tags,
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
        }
        try:
            supabase.table("assets").insert(row).execute()
        except Exception:
            pass
    # Log event
    log_event(
        tenant_id,
        brand,
        "asset_added",
        {
            "asset_id": asset_id,
            "phase_id": req.phase_id,
            "url": req.url,
            "type": req.type,
            "tags": req.tags,
        },
    )
    return asset


@app.get(
    "/tenant/{tenant_id}/brand/{brand_id}/assets",
    summary="List assets for a brand",
)
def list_assets(tenant_id: str, brand_id: str, phase_id: Optional[str] = None):
    """
    Retrieve all assets for a brand. You can optionally pass
    ``phase_id`` as a query parameter to filter assets belonging to a
    specific phase. The returned list contains asset metadata such as
    id, phase_id, url, type and tags. Assets are stored in the
    in‑memory ``BrandData.assets`` map; when Supabase is configured
    assets are also persisted to the ``assets`` table but this endpoint
    reads from memory. In the future you could extend this to
    query Supabase directly.
    """
    tenant = get_tenant(tenant_id)
    brand = tenant.brands.get(brand_id)
    if not brand:
        raise HTTPException(status_code=404, detail="Brand not found")
    assets = list(brand.assets.values())
    if phase_id:
        assets = [a for a in assets if a.get("phase_id") == phase_id]
    return assets


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)