-- Apply after the two-round migration. Idempotent and preserves prior jobs.
UPDATE event_config SET official_attempt_limit = 1 WHERE official_attempt_limit <> 1;
CREATE TABLE IF NOT EXISTS official_submission_claims (
    id BIGSERIAL PRIMARY KEY,
    team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    round_started_at TIMESTAMPTZ NOT NULL,
    job_id VARCHAR(36) NOT NULL UNIQUE,
    submission_id INTEGER NOT NULL REFERENCES submissions(id),
    source_sha256 VARCHAR(64) NOT NULL,
    CONSTRAINT uq_official_team_round UNIQUE (team_id, round_started_at)
);
CREATE INDEX IF NOT EXISTS ix_official_submission_claims_team_id ON official_submission_claims(team_id);
