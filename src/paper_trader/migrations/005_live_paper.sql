CREATE TABLE live_paper_state (
    id TEXT PRIMARY KEY,
    updated_at TEXT NOT NULL,
    payload_json TEXT NOT NULL
);

CREATE TABLE live_paper_events (
    id INTEGER PRIMARY KEY,
    created_at TEXT NOT NULL,
    event TEXT NOT NULL,
    payload_json TEXT NOT NULL
);

CREATE INDEX idx_live_paper_event ON live_paper_events(event, id);
