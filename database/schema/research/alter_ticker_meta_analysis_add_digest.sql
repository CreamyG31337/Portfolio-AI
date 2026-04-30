-- Apply on existing research DBs that already have ticker_meta_analysis (additive).
ALTER TABLE ticker_meta_analysis
    ADD COLUMN IF NOT EXISTS artifact_bundle_digest VARCHAR(64);

COMMENT ON COLUMN ticker_meta_analysis.artifact_bundle_digest IS
    'SHA-256 hex of canonical artifact bundle text; invalidates meta when upstream sources change';
