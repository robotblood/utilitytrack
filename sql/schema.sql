-- PostgreSQL target schema (deployment stage). Mirrors the JSON store 1:1.
CREATE TABLE utility (
    code        TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    services    TEXT[] NOT NULL,
    region      TEXT,
    status      TEXT NOT NULL CHECK (status IN ('active', 'planned'))
);

CREATE TABLE cost_driver (
    id           TEXT PRIMARY KEY,
    utility      TEXT NOT NULL REFERENCES utility(code),
    category     TEXT NOT NULL,
    direction    TEXT NOT NULL CHECK (direction IN ('up', 'down')),
    title        TEXT NOT NULL,
    sources      TEXT[] NOT NULL,
    verification TEXT NOT NULL DEFAULT 'needs_verification'
);

CREATE TABLE rate_action (
    id             TEXT PRIMARY KEY,
    utility        TEXT NOT NULL REFERENCES utility(code),
    service        TEXT NOT NULL CHECK (service IN ('electric', 'water', 'gas')),
    effective_date DATE NOT NULL,
    approved_date  DATE,
    status         TEXT NOT NULL,
    notes          TEXT,
    sources        TEXT[] NOT NULL,
    verification   TEXT NOT NULL DEFAULT 'needs_verification'
);

CREATE TABLE rate_change (
    id             BIGSERIAL PRIMARY KEY,
    action_id      TEXT NOT NULL REFERENCES rate_action(id) ON DELETE CASCADE,
    customer_class TEXT NOT NULL,
    metric         TEXT NOT NULL,
    value          NUMERIC(10, 3) NOT NULL
);

-- many-to-many: one action can have several causes, one cause can span years
CREATE TABLE rate_action_driver (
    action_id TEXT REFERENCES rate_action(id) ON DELETE CASCADE,
    driver_id TEXT REFERENCES cost_driver(id),
    PRIMARY KEY (action_id, driver_id)
);
