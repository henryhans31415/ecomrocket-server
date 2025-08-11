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