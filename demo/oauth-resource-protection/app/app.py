# Copyright (C) Dmitry Volyntsev
# Copyright (C) F5, Inc.

import json
import os
from pathlib import Path
import re
import secrets
import threading
import time
from urllib.parse import urlencode, urlsplit, urlunsplit

from authlib.integrations.requests_client import OAuth2Session
from flask import Flask, abort, jsonify, redirect, render_template, request
from flask import session
import requests

from scenarios import SCENARIOS, Scenarios, mcp_request


settings = json.loads(Path('/state/settings.json').read_text())
public = settings['public_url']
app = Flask(__name__)
app.secret_key = settings['secret']
app.config.update(SESSION_COOKIE_SECURE=True, SESSION_COOKIE_HTTPONLY=True,
                  SESSION_COOKIE_SAMESITE='Lax', MAX_CONTENT_LENGTH=8192)
records = {}
lock = threading.Lock()


def internal(url):
    parsed = urlsplit(url)
    origin = urlsplit(public)
    if (parsed.scheme, parsed.netloc) != (origin.scheme, origin.netloc):
        raise ValueError('Discovery endpoint is outside the demo origin')
    host = 'host.docker.internal:' + os.environ['DEMO_PORT']
    return urlunsplit(('https', host, parsed.path, parsed.query, ''))


def http(method, url, **kwargs):
    headers = kwargs.pop('headers', {})
    headers['Host'] = urlsplit(public).netloc
    try:
        return requests.request(method, internal(url), headers=headers,
                                verify='/state/certs/ca.crt', timeout=10,
                                allow_redirects=False, **kwargs)
    except requests.RequestException as error:
        raise ValueError('Demo endpoint request failed') from error


runner = Scenarios(settings, http)


def current():
    now = time.time()
    with lock:
        for key in list(records):
            if records[key]['expires'] < now:
                del records[key]
        key = session.get('id')
        if key not in records:
            if len(records) >= 128:
                abort(503)
            key = secrets.token_urlsafe(32)
            session['id'] = key
            records[key] = {'expires': now + 3600,
                            'csrf': secrets.token_urlsafe(32),
                            'steps': [], 'token': None, 'result': None}
        return records[key]


@app.before_request
def csrf():
    if request.method == 'POST':
        if secrets.compare_digest(request.headers.get('X-Demo-Control', ''),
                                  settings['secret']):
            return
        if not secrets.compare_digest(request.form.get('csrf', ''),
                                      current()['csrf']):
            abort(403)


def begin_login(record):
    headers, body = mcp_request()
    response = http('POST', public + '/mcp', headers=headers, json=body)
    if response.status_code != 401:
        raise ValueError('Expected the initial NGINX Bearer challenge')
    initial_challenge = response.headers.get('WWW-Authenticate', '')
    match = re.search(r'resource_metadata="([^"]+)"',
                      response.headers.get('WWW-Authenticate', ''))
    if not match:
        raise ValueError('Missing Protected Resource Metadata URL')
    metadata = http('GET', match[1])
    metadata.raise_for_status()
    resource = metadata.json()
    if resource['resource'] != public + '/mcp':
        raise ValueError('Resource metadata does not identify this MCP server')
    issuer = resource['authorization_servers'][0]
    # Try RFC 8414 first, then the OIDC discovery variants for path issuers.
    parsed = urlsplit(issuer)
    candidates = [
        public + '/.well-known/oauth-authorization-server' + parsed.path,
        public + '/.well-known/openid-configuration' + parsed.path,
        issuer + '/.well-known/openid-configuration',
    ]
    authorization = None
    for url in candidates:
        response = http('GET', url)
        if response.status_code == 200:
            authorization = response.json()
            break
    if not authorization or authorization.get('issuer') != issuer:
        raise ValueError('Authorization server metadata issuer mismatch')
    if 'S256' not in authorization.get('code_challenge_methods_supported', []):
        raise ValueError('IdP does not advertise PKCE S256')
    internal(authorization['authorization_endpoint'])
    internal(authorization['token_endpoint'])
    scope = resource.get('scopes_supported', [])
    challenged_scope = re.search(r'scope="([^"]*)"',
                                initial_challenge)
    if challenged_scope:
        scope = challenged_scope[1].split(' ')
    scope = list(dict.fromkeys(['openid', *scope]))
    verifier = secrets.token_urlsafe(48)
    client = OAuth2Session('mcp-demo', redirect_uri=public + '/callback',
                           scope=' '.join(scope), code_challenge_method='S256',
                           token_endpoint_auth_method='none')
    url, state = client.create_authorization_url(
        authorization['authorization_endpoint'], code_verifier=verifier,
        resource=resource['resource'])
    record['pending'] = {'state': state, 'verifier': verifier,
                         'metadata': authorization, 'issuer': issuer,
                         'resource': resource['resource'],
                         'expires': time.time() + 300}
    record['steps'] = [
        'MCP request without token → NGINX 401 + metadata URL',
        'Protected Resource Metadata → MCP resource and IdP issuer',
        'IdP discovery → validated issuer and PKCE S256',
        'Browser login/consent → waiting for callback',
    ]
    return url


@app.get('/')
def index():
    record = current()
    return render_template('index.html', scenarios=SCENARIOS, record=record)


@app.post('/login')
def login():
    return redirect(begin_login(current()))


@app.post('/api/login')
def api_login():
    return jsonify(url=begin_login(current()))


@app.get('/callback')
def callback():
    # CLI login arrives in a browser without the CLI session cookie.
    state = request.args.get('state', '')
    record = None
    with lock:
        for key, candidate in records.items():
            pending = candidate.get('pending', {})
            if pending and secrets.compare_digest(state, pending['state']):
                record = candidate
                session['id'] = key
                break
    if record is None:
        abort(400, 'Unknown OAuth state')
    pending = record.pop('pending')
    if pending['expires'] < time.time():
        abort(400, 'OAuth request expired')
    metadata = pending['metadata']
    issuer = request.args.get('iss')
    if ((metadata.get('authorization_response_iss_parameter_supported')
         and not issuer) or (issuer and issuer != pending['issuer'])):
        abort(400, 'Authorization response issuer mismatch')
    if request.args.get('error'):
        record['steps'].append('User authorization was declined')
        return redirect('/')
    code = request.args.get('code')
    if not code:
        abort(400, 'Missing authorization code')
    client = OAuth2Session('mcp-demo', redirect_uri=public + '/callback',
                           token_endpoint_auth_method='none')
    def token_response(response):
        if not response.headers.get('Content-Type', '').startswith(
                'application/json'):
            raise ValueError('IdP token endpoint returned HTTP '
                             + str(response.status_code))
        return response

    client.register_compliance_hook('access_token_response', token_response)
    token = client.fetch_token(
        internal(metadata['token_endpoint']), code=code,
        code_verifier=pending['verifier'], resource=pending['resource'],
        headers={'Host': urlsplit(public).netloc},
        verify='/state/certs/ca.crt', timeout=10)
    if token.get('token_type', '').lower() != 'bearer':
        abort(400, 'Expected a Bearer access token')
    if not token.get('id_token') or not metadata.get('end_session_endpoint'):
        abort(400, 'IdP must provide an ID token and logout endpoint')
    internal(metadata['end_session_endpoint'])
    record['end_session_endpoint'] = metadata['end_session_endpoint']
    record['token'] = token
    record['steps'].extend([
        'Callback → validated state and authorization response issuer',
        'Code + PKCE verifier + resource → access token',
    ])
    record['result'] = runner.run('allowed-call', token['access_token'])
    record['steps'].append('MCP retry → NGINX token/policy check → backend')
    return redirect('/')


def execute(name):
    record = current()
    bearer = (record['token'] or {}).get('access_token')
    result = runner.run(name, bearer)
    record['result'] = result
    return result


@app.post('/scenario/<name>')
def scenario(name):
    execute(name)
    return redirect('/')


@app.post('/api/scenario/<name>')
def api_scenario(name):
    return jsonify(execute(name))


@app.get('/api/status')
def status():
    record = current()
    return jsonify(authenticated=bool(record['token']),
                   steps=record['steps'], result=record['result'])


@app.post('/logout')
@app.post('/api/logout')
def logout():
    record = current()
    record['token'] = None
    record.pop('pending', None)
    record['steps'] = []
    record['result'] = None
    if request.path.startswith('/api/'):
        return jsonify(ok=True)
    return redirect('/')


@app.post('/idp-logout')
@app.post('/api/idp-logout')
def idp_logout():
    record = current()
    token = record['token'] or {}
    endpoint = record.get('end_session_endpoint')
    if not endpoint or not token.get('id_token'):
        raise ValueError('Log in first to obtain the IdP logout session')
    internal(endpoint)
    url = endpoint + '?' + urlencode({
        'id_token_hint': token['id_token'],
        'post_logout_redirect_uri': public + '/',
    })
    record['token'] = None
    record.pop('pending', None)
    record.pop('end_session_endpoint', None)
    record['steps'] = ['Application tokens cleared; browser logout at IdP']
    record['result'] = None
    if request.path.startswith('/api/'):
        return jsonify(url=url)
    return redirect(url)


@app.errorhandler(ValueError)
def invalid(error):
    return jsonify(error=str(error)), 400


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, threaded=True)
