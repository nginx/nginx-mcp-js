// Copyright (C) Dmitry Volyntsev
// Copyright (C) F5, Inc.

const MAX_BYTES = 65536;

function classify(message) {
    if (!message || typeof message !== 'object' || Array.isArray(message)
        || message.jsonrpc !== '2.0'
        || !Object.prototype.hasOwnProperty.call(message, 'id')
        || (message.id !== null && typeof message.id !== 'string'
            && typeof message.id !== 'number'))
    {
        return ['invalid_response', ''];
    }

    const hasResult = Object.prototype.hasOwnProperty.call(message, 'result');
    const hasError = Object.prototype.hasOwnProperty.call(message, 'error');

    if (hasResult === hasError) {
        return ['invalid_response', ''];
    }

    if (hasError) {
        const error = message.error;
        if (!error || !Number.isInteger(error.code)
            || typeof error.message !== 'string')
        {
            return ['invalid_response', ''];
        }
        const known = [-32700, -32600, -32601, -32602, -32603,
                       -32020, -32021, -32022];
        return ['rpc_error', known.includes(error.code)
                ? String(error.code) : 'other'];
    }

    const result = message.result;
    if (!result || typeof result !== 'object' || Array.isArray(result)) {
        return ['invalid_response', ''];
    }
    if (result.resultType === 'input_required') {
        if ((!result.inputRequests
             || typeof result.inputRequests !== 'object'
             || Array.isArray(result.inputRequests))
            && typeof result.requestState !== 'string')
        {
            return ['invalid_response', ''];
        }
        return ['input_required', ''];
    }
    if (result.resultType !== 'complete' || !Array.isArray(result.content)
        || (result.isError !== undefined
            && typeof result.isError !== 'boolean'))
    {
        return ['invalid_response', ''];
    }
    return [result.isError === true ? 'tool_error' : 'complete', ''];
}

function observe(r, data, flags) {
    r.sendBuffer(data, flags);

    const contentType = r.headersOut['Content-Type'] || '';
    if (!r.variables.upstream_status
        || !/^application\/json(?:\s*;|$)/i.test(contentType)
        || r.headersOut['Content-Encoding'])
    {
        delete r._mcpObserver;
        r.variables.mcp_outcome = 'unobserved';
        r.done();
        return;
    }

    let state = r._mcpObserver;
    if (state === undefined) {
        state = { chunks: [], bytes: 0 };
        r._mcpObserver = state;
    }

    if (data.length > MAX_BYTES - state.bytes) {
        delete r._mcpObserver;
        r.variables.mcp_outcome = 'unobserved';
        r.done();
        return;
    }
    if (data.length !== 0) {
        state.chunks.push(data);
        state.bytes += data.length;
    }

    if (!flags.last) {
        return;
    }

    delete r._mcpObserver;
    const body = state.chunks.length === 1 ? state.chunks[0]
                 : Buffer.concat(state.chunks, state.bytes);
    let outcome;
    try {
        outcome = classify(JSON.parse(body.toString('utf8')));
    } catch (e) {
        outcome = ['invalid_response', ''];
    }
    r.variables.mcp_outcome = outcome[0];
    r.variables.mcp_rpc_code = outcome[1];
    r.done();
}

export default { observe, classify };
