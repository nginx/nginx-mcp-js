# Copyright (C) Dmitry Volyntsev
# Copyright (C) F5, Inc.

import json
from pathlib import Path
import sys
import time

import requests

from scenarios import SCENARIOS


def main():
    settings = json.loads(Path('/state/settings.json').read_text())
    client = requests.Session()
    client.headers['X-Demo-Control'] = settings['secret']
    cookie_file = Path('/state/cli-cookie.json')
    if cookie_file.exists():
        # The API is called over local HTTP inside the application container.
        client.cookies.update(json.loads(cookie_file.read_text()))

    def api(path, method='POST'):
        response = client.request(method, 'http://127.0.0.1:8080/api/' + path,
                                  timeout=15)
        cookie_file.write_text(json.dumps(client.cookies.get_dict()))
        cookie_file.chmod(0o600)
        try:
            data = response.json()
        except ValueError:
            raise ValueError('Application returned HTTP '
                             + str(response.status_code)) from None
        if response.status_code != 200:
            raise ValueError(data.get('error', str(data)))
        # requests stores the Secure cookie but will not send it over HTTP.
        for cookie in client.cookies:
            cookie.secure = False
        return data

    def show(result):
        print('Scenario:', result['scenario'])
        print('HTTP:', result['http_status'])
        print('MCP outcome:', result['outcome'])
        reason = result['audit']['gateway']['reason'] or 'allowed'
        print('NGINX reason:', reason)
        print('Upstream attempted:', result['audit']['upstream']['attempted'])
        print('Verified subject:', result['audit']['auth']['subject'])
        print('Request ID:', result['request_id'])
        print('Check:', 'PASS' if result['passed'] else 'FAIL')
        for name, url in result['links'].items():
            print(name.capitalize() + ':', url)
        return result['passed']

    command = sys.argv[1] if len(sys.argv) > 1 else 'check'
    if command == 'login':
        api('logout')
        print('Open this URL in your browser:')
        print(api('login')['url'], flush=True)
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            data = api('status', 'GET')
            if data['authenticated']:
                for step in data['steps']:
                    print(step)
                return 0 if show(data['result']) else 1
            time.sleep(1)
        raise ValueError('Login timed out')
    if command == 'logout':
        api('logout')
        print('Application token cleared; IdP browser SSO is independent.')
        return 0
    if command == 'idp-logout':
        print('Application tokens cleared. Open this URL to end IdP SSO:')
        print(api('idp-logout')['url'])
        return 0
    if command == 'scenario':
        if len(sys.argv) != 3:
            raise ValueError('Choose: ' + ', '.join(SCENARIOS))
        return 0 if show(api('scenario/' + sys.argv[2])) else 1
    if command == 'check':
        names = ['no-token', 'fixture-call', 'insufficient-scope',
                 'expired-token', 'wrong-audience', 'bad-signature',
                 'wrong-issuer', 'missing-expiry', 'id-token', 'array-audience']
        passed = [show(api('scenario/' + name)) for name in names]
        return 0 if all(passed) else 1
    raise ValueError('Unknown CLI command')


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (ValueError, requests.RequestException) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
