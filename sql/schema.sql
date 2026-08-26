CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS products (
    product_id UUID PRIMARY KEY DEFAULT gen_random_uuid(), category VARCHAR(64) NOT NULL, brand VARCHAR(64) NOT NULL,
    model VARCHAR(128) NOT NULL, spec_identifiers JSONB, created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS assets (
    asset_id UUID PRIMARY KEY DEFAULT gen_random_uuid(), product_id UUID REFERENCES products(product_id),
    asset_fingerprint_hash VARCHAR(64) UNIQUE, created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS listings (
    listing_id VARCHAR(128) PRIMARY KEY, asset_id UUID REFERENCES assets(asset_id), product_id UUID REFERENCES products(product_id),
    connector_id VARCHAR(64) NOT NULL, listing_type VARCHAR(32) NOT NULL, title TEXT NOT NULL, listing_url TEXT,
    currency VARCHAR(8) NOT NULL DEFAULT 'USD', condition_grade VARCHAR(32), seller_id VARCHAR(128), seller_feedback_score INT,
    seller_feedback_percentage NUMERIC(6,3), seller_location VARCHAR(128), current_price NUMERIC(10,2) NOT NULL,
    shipping_cost NUMERIC(10,2) DEFAULT 0.00, sales_tax NUMERIC(10,2) DEFAULT 0.00, bid_count INT DEFAULT 0,
    watch_count INT DEFAULT 0, category_metadata JSONB DEFAULT '{}'::jsonb, raw_payload JSONB,
    first_seen_at TIMESTAMPTZ DEFAULT NOW(), last_updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS listing_snapshots (
    snapshot_id UUID PRIMARY KEY DEFAULT gen_random_uuid(), listing_id VARCHAR(128) REFERENCES listings(listing_id) ON DELETE CASCADE,
    price NUMERIC(10,2) NOT NULL, shipping_cost NUMERIC(10,2), bid_count INT, raw_payload JSONB, captured_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS comp_sets (
    comp_set_id UUID PRIMARY KEY DEFAULT gen_random_uuid(), listing_id VARCHAR(128) REFERENCES listings(listing_id) ON DELETE CASCADE,
    raw_comps_count INT, rejected_comps_count INT, used_comps_count INT, median_comp_price NUMERIC(10,2), weighted_comp_price NUMERIC(10,2),
    condition_penalty_pct NUMERIC(5,4), fast_sale_estimate NUMERIC(10,2), conservative_resale_estimate NUMERIC(10,2),
    expected_resale_estimate NUMERIC(10,2), optimistic_resale_estimate NUMERIC(10,2), confidence_score NUMERIC(5,4),
    comp_evidence_payload JSONB, calculated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS decisions (
    decision_id UUID PRIMARY KEY DEFAULT gen_random_uuid(), listing_id VARCHAR(128) REFERENCES listings(listing_id) ON DELETE CASCADE,
    decision_state VARCHAR(32) NOT NULL, confidence_score NUMERIC(5,4), safe_ceiling NUMERIC(10,2), normal_ceiling NUMERIC(10,2),
    aggressive_ceiling NUMERIC(10,2), expected_net_profit NUMERIC(10,2), evidence_ledger JSONB NOT NULL, evaluated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS auction_events (
    auction_id VARCHAR(128) PRIMARY KEY REFERENCES listings(listing_id) ON DELETE CASCADE, end_time TIMESTAMPTZ NOT NULL,
    state VARCHAR(32) NOT NULL, alert_offsets INT[] DEFAULT ARRAY[86400,3600,900,300], next_alert_at TIMESTAMPTZ,
    last_known_price NUMERIC(10,2), last_evaluated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS marketplace_connectors (
    connector_id VARCHAR(64) PRIMARY KEY, status VARCHAR(32) NOT NULL DEFAULT 'ACTIVE', rate_limit_state JSONB DEFAULT '{}'::jsonb,
    last_success_at TIMESTAMPTZ, last_failure_at TIMESTAMPTZ, failure_count INT DEFAULT 0
);

CREATE TABLE IF NOT EXISTS saved_searches (
    search_id UUID PRIMARY KEY DEFAULT gen_random_uuid(), connector_id VARCHAR(64) NOT NULL, query TEXT NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE, poll_interval_seconds INT NOT NULL DEFAULT 300 CHECK (poll_interval_seconds >= 30),
    max_price NUMERIC(10,2), category_id VARCHAR(128), filters JSONB NOT NULL DEFAULT '{}'::jsonb,
    next_poll_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), last_polled_at TIMESTAMPTZ, last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS saved_search_listings (
    search_id UUID REFERENCES saved_searches(search_id) ON DELETE CASCADE, listing_id VARCHAR(128) NOT NULL,
    fingerprint CHAR(64) NOT NULL, first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (search_id, listing_id)
);

CREATE INDEX IF NOT EXISTS idx_listings_product_id ON listings(product_id);
CREATE INDEX IF NOT EXISTS idx_listings_asset_id ON listings(asset_id);
CREATE INDEX IF NOT EXISTS idx_auction_events_next_alert ON auction_events(next_alert_at);
CREATE INDEX IF NOT EXISTS idx_decisions_listing_eval ON decisions(listing_id, evaluated_at DESC);
CREATE INDEX IF NOT EXISTS idx_saved_searches_due ON saved_searches(next_poll_at) WHERE enabled=TRUE;
CREATE INDEX IF NOT EXISTS idx_saved_search_listings_listing ON saved_search_listings(listing_id);
