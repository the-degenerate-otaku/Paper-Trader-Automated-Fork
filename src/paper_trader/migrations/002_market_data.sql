CREATE TABLE data_batches (
    version TEXT PRIMARY KEY,
    fetched_at TEXT NOT NULL,
    warnings_json TEXT NOT NULL
);

CREATE TABLE candle_versions (
    data_version TEXT NOT NULL REFERENCES data_batches(version),
    symbol TEXT NOT NULL REFERENCES instruments(symbol),
    timeframe TEXT NOT NULL,
    opened_at TEXT NOT NULL,
    closed_at TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    PRIMARY KEY (data_version, symbol, timeframe, opened_at)
);

CREATE TABLE action_versions (
    data_version TEXT NOT NULL REFERENCES data_batches(version),
    symbol TEXT NOT NULL REFERENCES instruments(symbol),
    ex_date TEXT NOT NULL,
    known_at TEXT NOT NULL,
    action_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    PRIMARY KEY (data_version, symbol, ex_date, action_type)
);

CREATE INDEX idx_candle_closed ON candle_versions(symbol, timeframe, closed_at);
CREATE INDEX idx_action_asof ON action_versions(symbol, known_at, ex_date);
