ALTER TABLE model_outputs ADD COLUMN checkpoint_revision TEXT NOT NULL DEFAULT 'unverified';

CREATE TABLE calibration_artifacts (
    id TEXT PRIMARY KEY,
    checkpoint_id TEXT NOT NULL,
    checkpoint_revision TEXT NOT NULL,
    created_at TEXT NOT NULL,
    report_json TEXT NOT NULL
);
