// Copyright (C) Dmitry Volyntsev
// Copyright (C) F5, Inc.

function claims(r) {
    let bearer = r.headersIn.Authorization || '';
    if (bearer.length > 8192 || !bearer.startsWith('Bearer ')) {
        return null;
    }
    try {
        let parts = bearer.slice(7).split('.');
        return {
            header: JSON.parse(Buffer.from(parts[0], 'base64url')),
            payload: JSON.parse(Buffer.from(parts[1], 'base64url')),
        };
    } catch (_) {
        return null;
    }
}

// auth_jwt evaluates this predicate only after signature/time validation.
function profile(r) {
    let token = claims(r);
    if (!token) {
        return '0';
    }
    let p = token.payload;
    if (!p || typeof p !== 'object' || !token.header) {
        return '0';
    }
    let audience = Array.isArray(p.aud) ? p.aud : [p.aud];
    return token.header.alg === 'RS256'
        && p.typ === 'Bearer'
        && p.iss === r.variables.mcp_issuer
        && audience.includes(r.variables.mcp_resource)
        && typeof p.exp === 'number'
        && Number.isFinite(p.exp)
        && typeof p.sub === 'string' && p.sub.length > 0
        ? '1' : '0';
}

function scopeAllowed(r) {
    let token = claims(r);
    let scope = token && token.payload && token.payload.scope;
    return typeof scope === 'string'
        && scope.split(' ').includes(r.variables.mcp_scope) ? '1' : '0';
}

function challenge(r) {
    if (r.variables.mcp_is_request !== '1') {
        return;
    }
    if (r.status === 401) {
        let error = r.headersIn.Authorization
            ? ', error="invalid_token"' : '';
        r.headersOut['WWW-Authenticate'] = 'Bearer resource_metadata="'
            + r.variables.mcp_metadata_url + '"' + error;
    } else if (r.status === 403
               && r.variables.mcp_rejection_reason === 'insufficient_scope') {
        r.headersOut['WWW-Authenticate'] = 'Bearer error="insufficient_scope", '
            + 'scope="' + r.variables.mcp_required_scope + '", '
            + 'resource_metadata="' + r.variables.mcp_metadata_url + '"';
    }
}

export default {profile, scopeAllowed, challenge};
