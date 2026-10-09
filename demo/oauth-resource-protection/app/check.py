# Copyright (C) Dmitry Volyntsev
# Copyright (C) F5, Inc.

from html.parser import HTMLParser
import base64
import json
from pathlib import Path
import time
from urllib.parse import parse_qs, urljoin, urlsplit

import requests


class Form(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.action = None
        self.fields = {}
        self.feed(text)

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if tag == 'form' and self.action is None:
            self.action = attrs.get('action')
        if tag == 'input' and attrs.get('name'):
            self.fields[attrs['name']] = attrs.get('value', '')


def main():
    settings = json.loads(Path('/state/settings.json').read_text())
    public = settings['public_url']
    browser = requests.Session()
    browser.verify = '/state/certs/ca.crt'
    # The checker runs with host networking; localhost is the real gateway.
    response = browser.get(public + '/', timeout=10)
    response.raise_for_status()
    form = Form(response.text)
    response = browser.post(public + '/login',
                            data={'csrf': form.fields['csrf']}, timeout=10)
    response.raise_for_status()
    login = Form(response.text)
    assert '/idp/' in response.url, response.url
    assert login.action, 'Missing IdP login form'
    data = dict(login.fields, username='alice', password='alice')
    response = browser.post(urljoin(response.url, login.action),
                            data=data, timeout=15)
    response.raise_for_status()
    if '/idp/' in response.url:
        consent = Form(response.text)
        if consent.action:
            response = browser.post(urljoin(response.url, consent.action),
                                    data=dict(consent.fields, accept='Yes'),
                                    timeout=15)
            response.raise_for_status()
    status = browser.get(public + '/api/status', timeout=10).json()
    assert status['authenticated'], status
    assert status['result']['passed'], status['result']
    assert len(status['steps']) == 7, status['steps']
    print('PASS real IdP login, consent, state/issuer, PKCE and MCP retry')
    result = status['result']
    csrf = Form(browser.get(public + '/', timeout=10).text).fields['csrf']
    response = browser.post(public + '/api/scenario/spoofed-identity',
                            data={'csrf': csrf}, timeout=10)
    response.raise_for_status()
    assert response.json()['passed'], response.text
    print('PASS verified identity replaces caller headers; bearer stripped')

    cli = requests.Session()
    cli.verify = browser.verify
    cli.headers['X-Demo-Control'] = settings['secret']
    login_url = cli.post(public + '/api/login', timeout=10).json()['url']
    # Keep IdP SSO cookies, but remove the application cookie as on CLI login.
    for cookie in list(browser.cookies):
        if cookie.name == 'session' and cookie.path == '/':
            browser.cookies.clear(cookie.domain, cookie.path, cookie.name)
    response = browser.get(login_url, timeout=10)
    if '/idp/' in response.url:
        consent = Form(response.text)
        response = browser.post(urljoin(response.url, consent.action),
                                data=dict(consent.fields, accept='Yes'),
                                timeout=10)
    response.raise_for_status()
    cli_status = cli.get(public + '/api/status', timeout=10).json()
    assert cli_status['authenticated'] and cli_status['result']['passed']
    print('PASS CLI session receives browser callback without its cookie')
    csrf = Form(browser.get(public + '/', timeout=10).text).fields['csrf']
    response = browser.post(public + '/idp-logout',
                            data={'csrf': csrf}, timeout=10)
    response.raise_for_status()
    assert not browser.get(public + '/api/status', timeout=10).json()[
        'authenticated']
    csrf = Form(response.text).fields['csrf']
    response = browser.post(public + '/login', data={'csrf': csrf}, timeout=10)
    response.raise_for_status()
    assert 'username' in Form(response.text).fields, response.text
    print('PASS IdP logout ends SSO; next login requires credentials')
    # Finish the new login to keep subsequent scenario checks authenticated.
    login = Form(response.text)
    response = browser.post(urljoin(response.url, login.action),
                            data=dict(login.fields, username='alice',
                                      password='alice'), timeout=15)
    response.raise_for_status()
    if '/idp/' in response.url:
        consent = Form(response.text)
        response = browser.post(urljoin(response.url, consent.action),
                                data=dict(consent.fields, accept='Yes'),
                                timeout=15)
        response.raise_for_status()
    csrf = Form(browser.get(public + '/', timeout=10).text).fields['csrf']

    for name in ['no-token', 'fixture-call', 'insufficient-scope',
                 'expired-token', 'wrong-audience', 'bad-signature',
                 'wrong-issuer', 'missing-expiry', 'id-token',
                 'array-audience']:
        response = browser.post(public + '/api/scenario/' + name,
                                data={'csrf': csrf}, timeout=10)
        response.raise_for_status()
        assert response.json()['passed'], response.text
        print('PASS', name)

    assert browser.get(public + '/callback?state=unknown',
                       timeout=10).status_code == 400
    # Wrong issuer must be rejected before exchanging a code.
    response = browser.post(public + '/api/login', data={'csrf': csrf},
                            timeout=10)
    state = parse_qs(urlsplit(response.json()['url']).query)['state'][0]
    response = browser.get(public + '/callback', params={
        'state': state, 'iss': 'https://untrusted.example.test',
        'code': 'must-not-be-exchanged'}, timeout=10)
    assert response.status_code == 400
    assert browser.get(public + '/callback', params={
        'state': state, 'iss': public + '/idp/realms/mcp',
        'code': 'must-not-be-exchanged'}, timeout=10).status_code == 400
    print('PASS unknown state, issuer mismatch and callback replay rejection')

    request_id = result['request_id']
    trace_id = result['audit']['trace_id']
    if not trace_id:
        print('Trace checks disabled: set NGINX_OTEL_MODULE')
        return
    grafana = settings['grafana_url']
    auth = ('admin', 'admin')
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        response = requests.get(
            grafana + '/api/datasources/proxy/uid/mcp-audit-loki'
            + '/loki/api/v1/query_range',
            params={'query': '{service_name="nginx-mcp-edge"}'
                            + ' | request_id="' + request_id + '"',
                    'start': str(time.time_ns() - 900 * 10**9),
                    'end': str(time.time_ns()), 'limit': 10},
            auth=auth, timeout=10)
        trace = requests.get(
            grafana + '/api/datasources/proxy/uid/mcp-audit-tempo'
            + '/api/traces/' + trace_id, auth=auth, timeout=10)
        if response.ok and response.json()['data']['result'] and trace.ok:
            spans = [span for batch in trace.json().get('batches', [])
                     for scope in batch.get('scopeSpans', [])
                     for span in scope.get('spans', [])]
            if len(spans) >= 3:
                edge = next(s for s in spans
                            if s['name'].startswith('MCP gateway '))
                backend = next(s for s in spans
                               if s['name'] == 'MCP HTTP request')
                tool = next(s for s in spans
                            if s['name'] == 'tools/call get_forecast')
                assert backend['parentSpanId'] == edge['spanId']
                assert tool['parentSpanId'] == backend['spanId']
                assert base64.b64decode(edge['spanId']).hex() == (
                    result['audit']['span_id'])
                print('PASS Loki event and correlated edge/backend/tool trace')
                return
        time.sleep(1)
    raise AssertionError('Log/trace ingestion did not complete')


if __name__ == '__main__':
    main()
