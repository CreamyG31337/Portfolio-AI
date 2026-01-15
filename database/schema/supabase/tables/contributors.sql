-- Table: contributors
DROP TABLE IF EXISTS contributors CASCADE;

CREATE TABLE contributors (
    id UUID NOT NULL DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL,
    email VARCHAR(255),
    phone VARCHAR(50),
    address TEXT,
    kyc_status VARCHAR(50) DEFAULT 'pending'::character varying,
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now()
,
    PRIMARY KEY (id)
);

-- Indexes
CREATE UNIQUE INDEX contributors_email_key ON contributors (email);
CREATE INDEX idx_contributors_email ON contributors (email);
CREATE INDEX idx_contributors_name ON contributors (name);