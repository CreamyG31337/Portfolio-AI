-- Table: user_funds
DROP TABLE IF EXISTS user_funds CASCADE;

CREATE TABLE user_funds (
    id UUID NOT NULL DEFAULT uuid_generate_v4(),
    user_id UUID,
    fund_name VARCHAR(50) NOT NULL,
    created_at TIMESTAMP DEFAULT now(),
    fund_id INTEGER
,
    PRIMARY KEY (id)
);

-- Foreign Keys
ALTER TABLE user_funds ADD CONSTRAINT user_funds_fund_id_fkey FOREIGN KEY (fund_id) REFERENCES funds(id);
ALTER TABLE user_funds ADD CONSTRAINT user_funds_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id);

-- Indexes
CREATE INDEX idx_user_funds_fund_id ON user_funds (fund_id);
CREATE INDEX idx_user_funds_fund_name ON user_funds (fund_name);
CREATE INDEX idx_user_funds_user_id ON user_funds (user_id);
CREATE UNIQUE INDEX user_funds_user_id_fund_name_key ON user_funds (user_id, fund_name);