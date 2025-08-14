-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Create tables for LangGraph checkpointing
CREATE TABLE IF NOT EXISTS checkpoints (
    thread_id TEXT,
    checkpoint_id TEXT,
    parent_id TEXT,
    checkpoint JSONB,
    metadata JSONB,
    PRIMARY KEY (thread_id, checkpoint_id)
);

CREATE TABLE IF NOT EXISTS writes (
    thread_id TEXT,
    checkpoint_id TEXT,
    task_id TEXT,
    idx INTEGER,
    channel TEXT,
    value JSONB,
    PRIMARY KEY (thread_id, checkpoint_id, task_id, idx)
);

-- Create index for better performance
CREATE INDEX IF NOT EXISTS checkpoints_thread_id_idx ON checkpoints(thread_id);