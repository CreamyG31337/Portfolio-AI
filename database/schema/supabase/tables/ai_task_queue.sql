-- Table: ai_task_queue
DROP TABLE IF EXISTS ai_task_queue CASCADE;

CREATE TABLE ai_task_queue (
    id UUID NOT NULL DEFAULT gen_random_uuid(),
    analysis_type VARCHAR(40) NOT NULL,
    target_key VARCHAR(100) NOT NULL,
    payload JSONB,
    priority INTEGER NOT NULL DEFAULT 0,
    status VARCHAR(20) NOT NULL DEFAULT 'pending'::character varying,
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    last_error TEXT,
    last_error_class VARCHAR(40),
    leased_by VARCHAR(120),
    leased_backend VARCHAR(40),
    leased_until TIMESTAMP WITH TIME ZONE,
    available_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    enqueued_by VARCHAR(40),
    attempted_backends VARCHAR(40)[] NOT NULL DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    completed_at TIMESTAMP WITH TIME ZONE,
    PRIMARY KEY (id),
    CONSTRAINT ai_task_queue_attempts_nonnegative CHECK (attempts >= 0),
    CONSTRAINT ai_task_queue_max_attempts_positive CHECK (max_attempts > 0),
    CONSTRAINT ai_task_queue_status_check CHECK (
        status IN ('pending', 'leased', 'done', 'failed', 'cancelled')
    )
);

ALTER TABLE ai_task_queue ENABLE ROW LEVEL SECURITY;

-- Indexes
CREATE INDEX ai_task_queue_pending_idx
    ON ai_task_queue (status, priority DESC, created_at)
    WHERE status = 'pending';

CREATE INDEX ai_task_queue_lease_recovery_idx
    ON ai_task_queue (status, leased_until)
    WHERE status = 'leased';

CREATE INDEX ai_task_queue_type_status_idx
    ON ai_task_queue (analysis_type, status, target_key);

CREATE UNIQUE INDEX ai_task_queue_active_dedupe_idx
    ON ai_task_queue (analysis_type, target_key)
    WHERE status IN ('pending', 'leased');
