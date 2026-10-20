CREATE TABLE run_points (
    run_id TEXT NOT NULL REFERENCES runs(id),
    at TEXT NOT NULL,
    equity TEXT NOT NULL,
    exposure TEXT NOT NULL,
    benchmarks_json TEXT NOT NULL,
    PRIMARY KEY (run_id, at)
);
