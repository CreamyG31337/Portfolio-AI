-- Table: research_domain_health
DROP TABLE IF EXISTS research_domain_health CASCADE;

CREATE TABLE research_domain_health (
    domain TEXT NOT NULL,
    total_attempts INTEGER DEFAULT 0,
    total_successes INTEGER DEFAULT 0,
    total_failures INTEGER DEFAULT 0,
    consecutive_failures INTEGER DEFAULT 0,
    last_failure_reason TEXT,
    last_attempt_at TIMESTAMP,
    last_success_at TIMESTAMP,
    auto_blacklisted BOOLEAN DEFAULT false,
    auto_blacklisted_at TIMESTAMP,
    updated_at TIMESTAMP DEFAULT now()
,
    PRIMARY KEY (domain)
);

-- Indexes
CREATE INDEX idx_domain_health_blacklisted ON research_domain_health (auto_blacklisted, domain);
CREATE INDEX idx_domain_health_consecutive ON research_domain_health (consecutive_failures, domain);