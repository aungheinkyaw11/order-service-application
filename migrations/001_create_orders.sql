CREATE TABLE orders (
    id UUID PRIMARY KEY,
    symbol VARCHAR(32) NOT NULL CHECK (length(btrim(symbol)) > 0),
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    status VARCHAR(16) NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'filled')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX orders_status_idx ON orders (status);
