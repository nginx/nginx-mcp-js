// Copyright (C) Dmitry Volyntsev
// Copyright (C) F5, Inc.

import assert from 'node:assert/strict';
import breaker from '../njs/mcp-breaker.mjs';

let now = 10000;
const clock = Date.now;
Date.now = () => now;

class Dictionary {
    values = new Map();
    has(key) {
        const item = this.values.get(key);
        return item !== undefined && item.expires > now;
    }
    add(key, value, timeout) {
        if (this.has(key)) {
            return false;
        }
        this.values.set(key, { value, expires: now + timeout });
        return true;
    }
    incr(key, delta, initial, timeout) {
        this.add(key, initial, timeout);
        const item = this.values.get(key);
        item.value += delta;
        return item.value;
    }
}

globalThis.ngx = { shared: {
    mcp_breaker_open: new Dictionary(),
    mcp_breaker_failures: new Dictionary()
} };

function request(key, outcome = 'rpc_error', code = '-32603') {
    return { variables: {
        mcp_breaker_key: key, mcp_breaker_admission: 'passed',
        upstream_addr: '127.0.0.1:9001', upstream_status: '200',
        mcp_outcome: outcome, mcp_rpc_code: code
    }, warn() {} };
}

try {
    const r = request('backend:tool');
    assert.equal(breaker.admission(r), 'passed');
    for (const outcome of ['tool_error', 'input_required', 'unobserved',
                           'invalid_response']) {
        breaker.record(request('backend:tool', outcome));
    }
    breaker.record(request('backend:tool', 'rpc_error', '-32602'));
    breaker.record(r);
    breaker.record(r);
    assert.equal(breaker.admission(r), 'passed');
    now += 5000;
    breaker.record(r);
    assert.equal(breaker.admission(r), 'passed');
    breaker.record(r);
    breaker.record(r);
    assert.equal(breaker.admission(r), 'blocked');
    assert.equal(breaker.admission(request('backend:neighbor')), 'passed');
    now += 9999;
    breaker.record(r);
    assert.equal(breaker.admission(r), 'blocked');
    now++;
    assert.equal(breaker.admission(r), 'passed');
    const blocked = request('backend:tool');
    blocked.variables.mcp_breaker_admission = 'blocked';
    blocked.variables.upstream_status = '503';
    for (let i = 0; i < 4; i++) {
        breaker.record(blocked);
    }
    assert.equal(breaker.admission(r), 'passed');
    const transport = request('backend:transport');
    transport.variables.upstream_status = '502';
    for (let i = 0; i < 3; i++) {
        breaker.record(transport);
    }
    assert.equal(breaker.admission(transport), 'blocked');
    console.log('PASS breaker failure policy, window, isolation and cooldown');
} finally {
    Date.now = clock;
    delete globalThis.ngx;
}
