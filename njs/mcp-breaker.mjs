// Copyright (C) Dmitry Volyntsev
// Copyright (C) F5, Inc.

const WINDOW_MS = 5000;
const COOLDOWN_MS = 10000;
const FAILURE_THRESHOLD = 3;

function admission(r) {
    const key = r.variables.mcp_breaker_key;
    return key && ngx.shared.mcp_breaker_open.has(key) ? 'blocked' : 'passed';
}

function record(r) {
    const key = r.variables.mcp_breaker_key;
    if (!key || r.variables.mcp_breaker_admission !== 'passed'
        || !r.variables.upstream_addr)
    {
        return '';
    }

    const status = r.variables.upstream_status;
    const failed = /^(500|502|503|504)$/.test(status)
                   || (r.variables.mcp_outcome === 'rpc_error'
                       && r.variables.mcp_rpc_code === '-32603');
    if (!failed || ngx.shared.mcp_breaker_open.has(key)) {
        return '';
    }

    // Fixed windows make concurrent increments independent of TTL refresh.
    const windowKey = key + ':' + Math.floor(Date.now() / WINDOW_MS);
    const failures = ngx.shared.mcp_breaker_failures.incr(
        windowKey, 1, 0, WINDOW_MS * 2);
    if (failures >= FAILURE_THRESHOLD
        && ngx.shared.mcp_breaker_open.add(key, 'open', COOLDOWN_MS))
    {
        r.warn('MCP circuit opened: ' + key);
    }
    return '';
}

export default { admission, record };
