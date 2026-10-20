CREATE TABLE instruments (
    symbol TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    instrument_type TEXT NOT NULL CHECK (instrument_type IN ('EQUITY', 'INDEX', 'FUTURE', 'OPTION')),
    sector TEXT,
    isin TEXT,
    series TEXT,
    lot_size INTEGER NOT NULL CHECK (lot_size > 0),
    tick_size TEXT NOT NULL,
    expiry TEXT,
    strike TEXT,
    provider_symbol TEXT NOT NULL
);

CREATE TABLE universe_snapshots (
    id INTEGER PRIMARY KEY,
    index_symbol TEXT NOT NULL REFERENCES instruments(symbol),
    observed_at TEXT NOT NULL,
    source_url TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    member_count INTEGER NOT NULL CHECK (member_count > 0),
    UNIQUE (index_symbol, observed_at)
);

CREATE TABLE constituents_history (
    snapshot_id INTEGER NOT NULL REFERENCES universe_snapshots(id),
    symbol TEXT NOT NULL REFERENCES instruments(symbol),
    company_name TEXT NOT NULL,
    sector TEXT NOT NULL,
    isin TEXT NOT NULL,
    PRIMARY KEY (snapshot_id, symbol)
);

CREATE TABLE holidays (
    day TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    source TEXT NOT NULL
);

CREATE TABLE accounts (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    currency TEXT NOT NULL CHECK (currency = 'INR'),
    starting_capital_paise INTEGER NOT NULL CHECK (starting_capital_paise > 0),
    cash_paise INTEGER NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE candles (
    symbol TEXT NOT NULL REFERENCES instruments(symbol),
    timeframe TEXT NOT NULL,
    opened_at TEXT NOT NULL,
    closed_at TEXT NOT NULL,
    open TEXT NOT NULL,
    high TEXT NOT NULL,
    low TEXT NOT NULL,
    close TEXT NOT NULL,
    volume INTEGER NOT NULL CHECK (volume >= 0),
    adjusted_json TEXT,
    source TEXT NOT NULL,
    data_version TEXT NOT NULL,
    PRIMARY KEY (symbol, timeframe, opened_at)
);

CREATE TABLE corporate_actions (
    id INTEGER PRIMARY KEY,
    symbol TEXT NOT NULL REFERENCES instruments(symbol),
    ex_date TEXT NOT NULL,
    action_type TEXT NOT NULL,
    details_json TEXT NOT NULL,
    observed_at TEXT NOT NULL
);

CREATE TABLE bots (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    account_id TEXT NOT NULL REFERENCES accounts(id),
    mode TEXT NOT NULL CHECK (mode IN ('manual', 'copilot', 'autopilot', 'shadow')),
    enabled INTEGER NOT NULL DEFAULT 0 CHECK (enabled IN (0, 1))
);

CREATE TABLE bot_configs (
    id INTEGER PRIMARY KEY,
    bot_id TEXT NOT NULL REFERENCES bots(id),
    config_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE runs (
    id TEXT PRIMARY KEY,
    config_json TEXT NOT NULL,
    data_version TEXT NOT NULL,
    checkpoint_id TEXT NOT NULL,
    random_seed INTEGER NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT
);

CREATE TABLE decisions (
    id TEXT PRIMARY KEY,
    run_id TEXT REFERENCES runs(id),
    bot_id TEXT REFERENCES bots(id),
    symbol TEXT NOT NULL REFERENCES instruments(symbol),
    created_at TEXT NOT NULL,
    state_text TEXT NOT NULL,
    features_json TEXT NOT NULL,
    policy_outcome TEXT NOT NULL,
    veto_reasons_json TEXT NOT NULL,
    checkpoint_id TEXT NOT NULL
);

CREATE TABLE model_outputs (
    id INTEGER PRIMARY KEY,
    decision_id TEXT NOT NULL REFERENCES decisions(id),
    request_json TEXT NOT NULL,
    response_json TEXT,
    latency_ms REAL,
    error TEXT
);

CREATE TABLE orders (
    id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES accounts(id),
    decision_id TEXT REFERENCES decisions(id),
    symbol TEXT NOT NULL REFERENCES instruments(symbol),
    side TEXT NOT NULL CHECK (side IN ('BUY', 'SELL')),
    product TEXT NOT NULL CHECK (product IN ('MIS', 'CNC')),
    order_type TEXT NOT NULL,
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    status TEXT NOT NULL,
    details_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE charges_config (
    id TEXT PRIMARY KEY,
    effective_date TEXT NOT NULL,
    rates_json TEXT NOT NULL,
    verified_source TEXT NOT NULL
);

CREATE TABLE fills (
    id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL REFERENCES orders(id),
    filled_at TEXT NOT NULL,
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    price TEXT NOT NULL,
    charges_paise INTEGER NOT NULL CHECK (charges_paise >= 0),
    charges_json TEXT NOT NULL,
    charges_config_id TEXT NOT NULL REFERENCES charges_config(id)
);

CREATE TABLE positions (
    account_id TEXT NOT NULL REFERENCES accounts(id),
    symbol TEXT NOT NULL REFERENCES instruments(symbol),
    product TEXT NOT NULL CHECK (product IN ('MIS', 'CNC')),
    quantity INTEGER NOT NULL CHECK (quantity != 0),
    average_price TEXT NOT NULL,
    stop_price TEXT NOT NULL,
    target_price TEXT,
    PRIMARY KEY (account_id, symbol, product),
    CHECK (product != 'CNC' OR quantity > 0)
);

CREATE TABLE trades (
    id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES accounts(id),
    symbol TEXT NOT NULL REFERENCES instruments(symbol),
    opened_at TEXT NOT NULL,
    closed_at TEXT,
    pnl_paise INTEGER,
    outcome_tag TEXT,
    details_json TEXT NOT NULL
);

CREATE TABLE metrics (
    run_id TEXT NOT NULL REFERENCES runs(id),
    name TEXT NOT NULL,
    dimensions_json TEXT NOT NULL,
    value REAL,
    PRIMARY KEY (run_id, name, dimensions_json)
);

CREATE TABLE journal (
    id INTEGER PRIMARY KEY,
    decision_id TEXT REFERENCES decisions(id),
    trade_id TEXT REFERENCES trades(id),
    created_at TEXT NOT NULL,
    body TEXT NOT NULL
);

CREATE TABLE lessons (
    id INTEGER PRIMARY KEY,
    trade_id TEXT NOT NULL REFERENCES trades(id),
    created_at TEXT NOT NULL,
    body TEXT NOT NULL
);

CREATE TABLE news (
    id TEXT PRIMARY KEY,
    symbol TEXT REFERENCES instruments(symbol),
    published_at TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    headline TEXT NOT NULL,
    source_url TEXT NOT NULL
);

CREATE TABLE audit_log (
    id INTEGER PRIMARY KEY,
    created_at TEXT NOT NULL,
    event TEXT NOT NULL,
    payload_json TEXT NOT NULL
);

CREATE INDEX idx_universe_asof ON universe_snapshots(index_symbol, observed_at);
CREATE INDEX idx_decisions_time ON decisions(symbol, created_at);
CREATE INDEX idx_news_time ON news(symbol, published_at, observed_at);
