-- Schema for persistent data storage via Supabase

-- Table to persist user progress through programs and sequences.
-- This table stores the current sequence and task indices as well as
-- accumulated XP, levels, streak data and badges. It does not
-- replicate the program/sequence/task definitions from sequences.json.
-- You must enable the pgcrypto extension in your database to use
-- gen_random_uuid().

-- Enable the pgcrypto extension for gen_random_uuid() if not already enabled.
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Create the user_progress table. This table lives in the public schema
-- so that the auto-generated PostgREST API can access it. You should
-- apply row level security (RLS) policies if exposing this table
-- directly to clients.
CREATE TABLE IF NOT EXISTS user_progress (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    user_id UUID NOT NULL,
    program_id TEXT NOT NULL,
    -- Index of the current sequence within the program's sequence order
    current_sequence_index INTEGER NOT NULL DEFAULT 0,
    -- Index of the current task within the current sequence's task list
    current_task_index INTEGER NOT NULL DEFAULT 0,
    xp INTEGER NOT NULL DEFAULT 0,
    level INTEGER NOT NULL DEFAULT 1,
    streak_days INTEGER NOT NULL DEFAULT 0,
    last_completed_at TIMESTAMP WITH TIME ZONE,
    badges JSONB NOT NULL DEFAULT '[]',
    unlocked_sequences JSONB NOT NULL DEFAULT '{}',
    mentorship_eligible BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
);

-- Table to store brands. Each brand belongs to a tenant and can be
-- displayed separately in the dashboard. A brand corresponds to a
-- product or business launch.
CREATE TABLE IF NOT EXISTS brands (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    name TEXT NOT NULL,
    color_token TEXT,
    logo_url TEXT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
);

-- Table to store phases within a brand. Phases are ordered via
-- phase_order and grouped under a brand. The key field is used as
-- a short identifier (e.g. "company_setup").
CREATE TABLE IF NOT EXISTS phases (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    brand_id UUID NOT NULL,
    key TEXT NOT NULL,
    name TEXT NOT NULL,
    phase_order INTEGER NOT NULL,
    weight INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    CONSTRAINT unique_phase_key_per_brand UNIQUE (brand_id, key)
);

-- Table to store tasks within a phase. Tasks can depend on other
-- tasks (depicted via the JSON array depends_on) and have an
-- optional duration to drive schedule calculations.
CREATE TABLE IF NOT EXISTS phase_tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    brand_id UUID NOT NULL,
    phase_id UUID NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    duration_days INTEGER,
    weight INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'todo',
    depends_on JSONB NOT NULL DEFAULT '[]',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    CONSTRAINT unique_task_name_per_phase UNIQUE (phase_id, name)
);

-- Event log table to capture significant changes (e.g. task completion,
-- blockers, schedule shifts) for "today's pulse" digests. Payload
-- stores details as JSON.
CREATE TABLE IF NOT EXISTS events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    brand_id UUID NOT NULL,
    type TEXT NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
);