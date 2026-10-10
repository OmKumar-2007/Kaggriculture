-- Additive PostgreSQL migration. Existing teams, submissions, scores and jobs stay intact.
ALTER TABLE event_config ADD COLUMN IF NOT EXISTS qualifier_count INTEGER NOT NULL DEFAULT 16;
ALTER TABLE event_config ADD COLUMN IF NOT EXISTS registration_capacity INTEGER NOT NULL DEFAULT 100;
ALTER TABLE event_config ADD COLUMN IF NOT EXISTS official_attempt_limit INTEGER NOT NULL DEFAULT 1;
UPDATE event_config SET official_attempt_limit = 1 WHERE official_attempt_limit <> 1;
ALTER TABLE event_config ADD COLUMN IF NOT EXISTS reference_count INTEGER NOT NULL DEFAULT 5;
ALTER TABLE event_config ADD COLUMN IF NOT EXISTS qualification_seed_count INTEGER NOT NULL DEFAULT 2;
ALTER TABLE event_config ADD COLUMN IF NOT EXISTS tie_replay_limit INTEGER NOT NULL DEFAULT 3;

ALTER TABLE evaluations ADD COLUMN IF NOT EXISTS average_opponent_money FLOAT;
ALTER TABLE evaluations ADD COLUMN IF NOT EXISTS economic_score FLOAT;
ALTER TABLE evaluations ADD COLUMN IF NOT EXISTS losses INTEGER;

CREATE TABLE IF NOT EXISTS competition_state (
    id INTEGER PRIMARY KEY,
    phase VARCHAR(40) NOT NULL DEFAULT 'SETUP',
    reference_snapshot_json TEXT NOT NULL DEFAULT '[]',
    evaluation_config_json TEXT NOT NULL DEFAULT '{}',
    qualifier_roster_json TEXT NOT NULL DEFAULT '[]',
    standings_json TEXT NOT NULL DEFAULT '[]',
    started_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS reference_bots (
    id SERIAL PRIMARY KEY,
    family_id VARCHAR(36) NOT NULL,
    version INTEGER NOT NULL,
    display_name VARCHAR(120) NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    category VARCHAR(80) NOT NULL DEFAULT '',
    object_key TEXT NOT NULL,
    source_sha256 VARCHAR(64) NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    selected BOOLEAN NOT NULL DEFAULT FALSE,
    archived BOOLEAN NOT NULL DEFAULT FALSE,
    validation_status VARCHAR(20) NOT NULL DEFAULT 'valid',
    test_status VARCHAR(20) NOT NULL DEFAULT 'untested',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_reference_family_version UNIQUE (family_id, version)
);
CREATE INDEX IF NOT EXISTS ix_reference_bots_family_id ON reference_bots(family_id);

CREATE TABLE IF NOT EXISTS tournament_games (
    game_id VARCHAR(80) PRIMARY KEY,
    match_id VARCHAR(40) NOT NULL,
    round_number INTEGER NOT NULL,
    replay_number INTEGER NOT NULL,
    leg INTEGER NOT NULL,
    seed INTEGER NOT NULL,
    player_zero VARCHAR(80) NOT NULL,
    player_one VARCHAR(80) NOT NULL,
    score_zero FLOAT NOT NULL,
    score_one FLOAT NOT NULL,
    replay_id VARCHAR(64),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_tournament_games_match_id ON tournament_games(match_id);
