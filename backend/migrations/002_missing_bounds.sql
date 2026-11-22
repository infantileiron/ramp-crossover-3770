-- 缺测推演：单人用时范围（用时规则）与每轮全员总用时，均为可版本化的现场约束。
CREATE TABLE IF NOT EXISTS timing_rule (
    id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    route_code text NOT NULL REFERENCES field_route(code),
    min_seconds numeric(7,2) NOT NULL CHECK (min_seconds > 0 AND min_seconds <= 900),
    max_seconds numeric(7,2) NOT NULL CHECK (max_seconds > 0 AND max_seconds <= 900),
    updated_by text NOT NULL REFERENCES app_user(username),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (min_seconds <= max_seconds)
);

CREATE TABLE IF NOT EXISTS round_total (
    route_code text NOT NULL REFERENCES field_route(code),
    period integer NOT NULL CHECK (period IN (1, 2)),
    total_seconds numeric(9,2) NOT NULL CHECK (total_seconds > 0 AND total_seconds <= 12000),
    updated_by text NOT NULL REFERENCES app_user(username),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (route_code, period)
);

-- 现场约束代际：用时规则或任一轮总用时更新都会 +1，作为结论时效依据。
CREATE TABLE IF NOT EXISTS constraint_ledger (
    route_code text PRIMARY KEY REFERENCES field_route(code),
    generation integer NOT NULL DEFAULT 0 CHECK (generation >= 0)
);

-- 每条路线至多一条现行用时规则（历史更新在审计事件中留痕）。
CREATE UNIQUE INDEX IF NOT EXISTS timing_rule_one_active ON timing_rule (route_code);
