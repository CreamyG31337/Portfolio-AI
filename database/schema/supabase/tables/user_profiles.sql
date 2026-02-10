-- Table: user_profiles
DROP TABLE IF EXISTS user_profiles CASCADE;

CREATE TABLE user_profiles (
    id UUID NOT NULL DEFAULT uuid_generate_v4(),
    user_id UUID,
    email VARCHAR(255) NOT NULL,
    full_name VARCHAR(255),
    role VARCHAR(50) DEFAULT 'user'::character varying,
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now(),
    preferences JSONB DEFAULT '{}'::jsonb
,
    PRIMARY KEY (id)
);

-- Foreign Keys
ALTER TABLE user_profiles ADD CONSTRAINT user_profiles_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id);

-- Indexes
CREATE INDEX idx_user_profiles_preferences ON user_profiles (preferences);
CREATE INDEX idx_user_profiles_user_id ON user_profiles (user_id);
CREATE UNIQUE INDEX user_profiles_user_id_key ON user_profiles (user_id);