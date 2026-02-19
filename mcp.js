var _mcp_messages = [];
var _mcp_buffer = "";

function mcp_header_filter(r) {
    delete r.headersOut['Content-Length'];

    var body = JSON.parse(r.requestText || '{}');
    if (body.method === 'initialize') {
        var sessionId = r.headersOut['Mcp-Session-Id'];
        var clientName = body.params
                         && body.params.clientInfo
                         && body.params.clientInfo.name;

        if (sessionId && clientName) {
            ngx.shared.mcp_clients.set(sessionId, clientName);
        }
    }
}

function parse_sse_first_json(buffer) {
    var sse_messages = buffer.split(/\n\n/);
    for (var i = 0; i < sse_messages.length; i++) {
        var block = sse_messages[i].trim();
        if (!block) {
            continue;
        }

        var lines = block.split(/\n/);
        for (var j = 0; j < lines.length; j++) {
            var line = lines[j];
            if (line.startsWith("data: ")) {
                try {
                    return JSON.parse(line.substring(6));
                } catch (e) {
                }
            }
        }
    }

    return null;
}

function mcp_response_filter(r, data, flags) {
    _mcp_buffer += data;
    r.sendBuffer(data, flags);

    if (_mcp_messages.length > 0) {
        return;
    }

    var json_obj = parse_sse_first_json(_mcp_buffer);
    if (!json_obj) {
        return;
    }

    _mcp_messages.push(json_obj);

    if (json_obj.result && json_obj.result.serverInfo) {
        var sid = r.headersOut['Mcp-Session-Id'];
        var name = json_obj.result.serverInfo.name;
        if (sid && name) {
            ngx.shared.mcp_servers.set(sid, name);
        }
    }

    r.done();
}

function getPath(r, json_obj, path) {
    if (!json_obj) {
        return undefined;
    }

    var parts = path.split('.');
    var current = json_obj;
    for (var i = 0; i < parts.length; i++) {
        var part = parts[i];
        if (typeof current !== 'object'
            || current === null
            || !current.hasOwnProperty(part))
        {
            return undefined;
        }

        current = current[part];
    }

    return current;
}

function has_error(r) {
    if (_mcp_messages.length === 0) {
        return false;
    }

    var first_message = _mcp_messages[0];

    if (getPath(r, first_message, "error")) {
        return true;
    }

    if (getPath(r, first_message, "result.isError")) {
        return true;
    }

    return false;
}

function mcp_tool_name(r) {
    var body = JSON.parse(r.requestText || '{}');
    var method = body.method;
    if (method == 'tools/call') {
        return body.params.name;
    }

    return '';
}

function mcp_server_name(r) {
    var sessionId = r.headersIn['Mcp-Session-Id'];
    if (sessionId) {
        return ngx.shared.mcp_servers.get(sessionId) || '';
    }

    return '';
}

function mcp_client_name(r) {
    var sessionId = r.headersIn['Mcp-Session-Id'];
    if (sessionId) {
        return ngx.shared.mcp_clients.get(sessionId) || '';
    }

    return '';
}

function mcp_tool_status(r) {
    if (has_error(r)) {
        return 'error';
    }

    return 'ok';
}

export default {
    mcp_response_filter, mcp_header_filter,
    mcp_tool_name, mcp_tool_status,
    mcp_client_name, mcp_server_name
};
