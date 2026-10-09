# Copyright (C) Dmitry Volyntsev
# Copyright (C) F5, Inc.

import json
from pathlib import Path
import time
from urllib.parse import urlencode

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
import requests

import jwt_utils


SCENARIOS = {
    'no-token': ('Call without a token', 401),
    'allowed-call': ('Call with the token obtained by browser login', 200),
    'insufficient-scope': ('Call translation with only mcp:tools', 403),
    'spoofed-identity': ('Supply X-User: mallory with a valid token', 200),
    'expired-token': ('Use a signed, expired fixture token', 401),
    'wrong-audience': ('Use a signed token intended for another API', 401),
    'bad-signature': ('Use a token signed by an untrusted key', 401),
    'fixture-call': ('Call with a locally signed test fixture', 200),
    'wrong-issuer': ('Use a signed token with an untrusted issuer', 401),
    'missing-expiry': ('Use a signed token without a numeric expiry', 401),
    'id-token': ('Supply an ID-token profile instead of an access token', 401),
    'array-audience': ('Use an access token with an audience array', 200),
}


def mcp_request(name='get_forecast', bearer=None, spoof=False):
    headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json, text/event-stream',
        'Mcp-Protocol-Version': '2026-07-28',
        'Mcp-Method': 'tools/call', 'Mcp-Name': name,
    }
    if bearer:
        headers['Authorization'] = 'Bearer ' + bearer
    if spoof:
        headers['X-User'] = 'mallory'
        headers['X-Tenant'] = 'attacker'
    body = {
        'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
        'params': {'name': name, 'arguments': {}, '_meta': {
            'io.modelcontextprotocol/protocolVersion': '2026-07-28',
            'io.modelcontextprotocol/clientCapabilities': {},
            'io.modelcontextprotocol/clientInfo': {
                'name': 'oauth-demo', 'version': '1.0',
            },
        }},
    }
    return headers, body


class Scenarios:
    def __init__(self, settings, http):
        self.settings = settings
        self.http = http
        self.key = serialization.load_pem_private_key(
            Path('/state/fixture.key').read_bytes(), None)

    def audit(self, request_id):
        path = Path('/state/logs/mcp.json')
        for _ in range(30):
            if path.exists():
                # Read only the recent tail; never accumulate the entire log.
                with path.open('rb') as stream:
                    stream.seek(max(0, path.stat().st_size - 256 * 1024))
                    lines = stream.read().splitlines()
                for line in reversed(lines):
                    try:
                        record = json.loads(line)
                    except ValueError:
                        continue
                    if record.get('request_id') == request_id:
                        return record
            time.sleep(0.1)
        raise ValueError('NGINX audit event did not arrive')

    def run(self, name, access_token=None):
        if name not in SCENARIOS:
            raise ValueError('Unknown scenario')
        bearer = access_token
        public = self.settings['public_url']
        if name == 'no-token':
            bearer = None
        elif name in ('allowed-call', 'spoofed-identity'):
            if not bearer:
                raise ValueError('Run login first')
        else:
            overrides = {}
            if name == 'expired-token':
                overrides['exp'] = int(time.time()) - 60
            elif name == 'wrong-audience':
                overrides['aud'] = 'https://other.example.test/api'
            elif name == 'wrong-issuer':
                overrides['iss'] = 'https://untrusted.example.test'
            elif name == 'missing-expiry':
                overrides['exp'] = None
            elif name == 'id-token':
                overrides['typ'] = 'ID'
            elif name == 'array-audience':
                overrides['aud'] = [public + '/mcp', 'other-resource']
            key = self.key
            if name == 'bad-signature':
                key = rsa.generate_private_key(
                    public_exponent=65537, key_size=2048)
            bearer = jwt_utils.token(key, public, **overrides)
        tool = ('translate_text' if name == 'insufficient-scope'
                else 'get_forecast')
        headers, body = mcp_request(tool, bearer, name == 'spoofed-identity')
        response = self.http('POST', public + '/mcp',
                             headers=headers, json=body)
        request_id = response.headers.get('X-Request-ID', '')
        if not request_id:
            raise ValueError('Missing NGINX request ID')
        record = self.audit(request_id)
        expected = SCENARIOS[name][1]
        passed = response.status_code == expected
        attempted = record['upstream']['attempted']
        passed = passed and attempted == (expected == 200)
        challenge = response.headers.get('WWW-Authenticate', '')
        if expected == 401:
            passed = passed and 'resource_metadata="' in challenge
            passed = passed and record['auth']['subject'] == ''
        if expected == 403:
            passed = passed and 'error="insufficient_scope"' in challenge
        outcome = 'not_executed'
        result = None
        if expected == 200 and response.status_code == 200:
            result = response.json()
            outcome = ('rpc_error' if 'error' in result else
                       'tool_error' if result.get('result', {}).get('isError')
                       else 'complete')
            passed = passed and outcome == 'complete'
            passed = passed and response.headers.get(
                'X-Demo-Received-User') == record['auth']['subject']
            passed = passed and not response.headers.get(
                'X-Demo-Received-Authorization')
            if name == 'spoofed-identity':
                passed = passed and response.headers.get(
                    'X-Demo-Received-Tenant') != 'attacker'
        grafana = self.settings['grafana_url']
        params = urlencode({'var-request_id': request_id,
                            'from': 'now-15m', 'to': 'now'})
        trace_id = record.get('trace_id', '')
        links = {'audit': grafana + '/d/mcp-searchable-audit?' + params}
        if trace_id:
            panes = {'mcp': {'datasource': 'mcp-audit-tempo',
                              'queries': [{'refId': 'A', 'query': trace_id,
                                           'datasource': {
                                               'type': 'tempo',
                                               'uid': 'mcp-audit-tempo',
                                           },
                                           'queryType': 'traceql'}],
                              'range': {'from': 'now-15m', 'to': 'now'}}}
            links['trace'] = grafana + '/explore?' + urlencode({
                'schemaVersion': 1, 'panes': json.dumps(panes)})
        return {'scenario': name, 'expected_http': expected,
                'http_status': response.status_code, 'outcome': outcome,
                'request_id': request_id, 'challenge': challenge,
                'passed': bool(passed), 'audit': record, 'links': links,
                'result': result}
