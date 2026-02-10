-- Table: system_settings
DROP TABLE IF EXISTS system_settings CASCADE;

CREATE TABLE system_settings (
    key TEXT NOT NULL,
    value JSONB NOT NULL,
    description TEXT,
    updated_at TIMESTAMP DEFAULT now(),
    updated_by UUID
,
    PRIMARY KEY (key)
);

-- Foreign Keys
ALTER TABLE system_settings ADD CONSTRAINT system_settings_updated_by_fkey FOREIGN KEY (updated_by) REFERENCES users(id);

-- Indexes
CREATE INDEX idx_system_settings_updated_at ON system_settings (updated_at);