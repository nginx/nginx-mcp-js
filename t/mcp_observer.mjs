// Copyright (C) Dmitry Volyntsev
// Copyright (C) F5, Inc.

import assert from 'node:assert/strict';
import observer from '../njs/mcp-observer.mjs';
const classify = observer.classify;

const complete = {
    jsonrpc: '2.0', id: 1,
    result: { resultType: 'complete', content: [] }
};
assert.equal(classify(complete)[0], 'complete');
assert.equal(classify({ ...complete, result: {
    ...complete.result, isError: true
} })[0], 'tool_error');
assert.equal(classify({ ...complete, result: {
    ...complete.result, isError: 'true'
} })[0], 'invalid_response');
assert.equal(classify({})[0], 'invalid_response');
assert.equal(classify({ ...complete, error: {} })[0], 'invalid_response');
assert.equal(classify({ jsonrpc: '2.0', id: 1,
    error: { code: -32603, message: 'failed' }
})[1], '-32603');
assert.equal(classify({ jsonrpc: '2.0', id: 1,
    error: { code: -99999, message: 'failed' }
})[1], 'other');

function request(type = 'application/json') {
    return {
        variables: { upstream_status: '200' },
        headersOut: { 'Content-Type': type },
        sent: [], done() {},
        sendBuffer(data) { this.sent.push(data); }
    };
}

const body = Buffer.from(JSON.stringify({ ...complete, result: {
    ...complete.result, content: [{ type: 'text', text: '世界' }]
} }));
const r = request();
for (let i = 0; i < body.length; i++) {
    observer.observe(r, body.subarray(i, i + 1), {
        last: i === body.length - 1
    });
}
assert.equal(r.variables.mcp_outcome, 'complete');
assert.deepEqual(Buffer.concat(r.sent), body);
assert.equal(r._mcpObserver, undefined);
const partial = request();
observer.observe(partial, body.subarray(0, 1), { last: false });
const separate = request();
observer.observe(separate, body, { last: true });
observer.observe(partial, body.subarray(1), { last: true });
assert.equal(partial.variables.mcp_outcome, 'complete');
assert.equal(separate.variables.mcp_outcome, 'complete');
const large = request();
observer.observe(large, Buffer.alloc(65536), { last: false });
observer.observe(large, Buffer.alloc(1), { last: true });
assert.equal(large.variables.mcp_outcome, 'unobserved');
assert.equal(large._mcpObserver, undefined);
const sse = request('text/event-stream');
observer.observe(sse, body, { last: true });
assert.equal(sse.variables.mcp_outcome, 'unobserved');
const invalid = request();
observer.observe(invalid, Buffer.from('{'), { last: true });
assert.equal(invalid.variables.mcp_outcome, 'invalid_response');
const compressed = request();
compressed.headersOut['Content-Encoding'] = 'gzip';
observer.observe(compressed, body, { last: true });
assert.equal(compressed.variables.mcp_outcome, 'unobserved');
console.log('PASS classifier, split UTF-8, byte cap, response preservation');
