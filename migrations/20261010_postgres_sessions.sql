-- Optional Azure session backend. Existing Redis deployments remain unchanged.
CREATE TABLE IF NOT EXISTS participant_sessions (
    key_hash VARCHAR(64) PRIMARY KEY,
    team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    payload_json TEXT NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_participant_sessions_team_id ON participant_sessions(team_id);
CREATE INDEX IF NOT EXISTS ix_participant_sessions_expires_at ON participant_sessions(expires_at);
CREATE TABLE IF NOT EXISTS shared_rate_limits (
    key_hash VARCHAR(64) PRIMARY KEY,
    count INTEGER NOT NULL DEFAULT 0,
    expires_at TIMESTAMPTZ NOT NULL
);
