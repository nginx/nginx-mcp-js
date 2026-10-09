# Copyright (C) Dmitry Volyntsev
# Copyright (C) F5, Inc.

import datetime
import ipaddress
import json
import os
from pathlib import Path
import secrets
import sys
import time
from urllib.parse import urlsplit

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
import jwt_utils
import requests


STATE = Path('/state')
PUBLIC = os.environ['DEMO_PUBLIC_URL'].rstrip('/')
URL = urlsplit(PUBLIC)


def write(name, value, private=False):
    path = STATE / name
    path.write_text(value)
    path.chmod(0o600 if private else 0o644)


def certificates():
    if (STATE / 'certs/server.crt').exists():
        previous = json.loads((STATE / 'settings.json').read_text())
        if previous['public_url'] != PUBLIC:
            raise ValueError('Use a new OAUTH_STATE_DIR for a new public URL')
        existing = x509.load_pem_x509_certificate(
            (STATE / 'certs/server.crt').read_bytes())
        if existing.subject != existing.issuer and any(
                isinstance(ext.value, x509.AuthorityKeyIdentifier)
                for ext in existing.extensions):
            return
    now = datetime.datetime.now(datetime.timezone.utc)
    ca = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'MCP demo CA')])
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(ca.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(minutes=1))
            .not_valid_after(now + datetime.timedelta(days=30))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), True)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(
                ca.public_key()), False)
            .add_extension(x509.KeyUsage(
                digital_signature=False, content_commitment=False,
                key_encipherment=False, data_encipherment=False,
                key_agreement=False, key_cert_sign=True, crl_sign=True,
                encipher_only=None, decipher_only=None), True)
            .sign(ca, hashes.SHA256()))
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    hosts = [x509.DNSName('localhost'), x509.DNSName('host.docker.internal')]
    try:
        hosts.append(x509.IPAddress(ipaddress.ip_address(URL.hostname)))
    except ValueError:
        hosts.append(x509.DNSName(URL.hostname))
    server_name = x509.Name([x509.NameAttribute(
        NameOID.COMMON_NAME, URL.hostname)])
    server = (x509.CertificateBuilder().subject_name(server_name)
              .issuer_name(name)
              .public_key(key.public_key())
              .serial_number(x509.random_serial_number())
              .not_valid_before(now - datetime.timedelta(minutes=1))
              .not_valid_after(now + datetime.timedelta(days=30))
              .add_extension(
                  x509.SubjectAlternativeName(hosts), False)
              .add_extension(
                  x509.AuthorityKeyIdentifier.from_issuer_public_key(
                      ca.public_key()), False)
              .sign(ca, hashes.SHA256()))
    write('certs/ca.crt', cert.public_bytes(
        serialization.Encoding.PEM).decode())
    write('certs/server.crt', server.public_bytes(
        serialization.Encoding.PEM).decode())
    write('certs/server.key', key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()).decode(), True)


def prepare():
    if (URL.scheme != 'https' or not URL.hostname or URL.path
            or URL.query or URL.fragment or URL.username):
        raise ValueError('DEMO_PUBLIC_URL must be an HTTPS origin')
    certificates()
    secret = secrets.token_hex(32)
    if (STATE / 'settings.json').exists():
        secret = json.loads((STATE / 'settings.json').read_text())['secret']
    write('settings.json', json.dumps({
        'public_url': PUBLIC, 'secret': secret,
        'grafana_url': os.environ['GRAFANA_PUBLIC_URL'],
    }), True)
    if not (STATE / 'fixture.key').exists():
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        write('fixture.key', key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption()).decode(), True)
    key = serialization.load_pem_private_key(
        (STATE / 'fixture.key').read_bytes(), None)
    write('fixture-jwks.json', json.dumps({'keys': [jwt_utils.jwk(key)]}))
    realm = {
        'realm': 'mcp', 'enabled': True, 'sslRequired': 'external',
        'accessTokenLifespan': 300,
        'users': [{'username': 'alice', 'enabled': True,
                   'email': 'alice@example.test', 'emailVerified': True,
                   'firstName': 'Alice', 'lastName': 'Demo',
                   'credentials': [{'type': 'password', 'value': 'alice',
                                    'temporary': False}]}],
        'clientScopes': [
            {'name': 'mcp:tools', 'protocol': 'openid-connect',
             'attributes': {'include.in.token.scope': 'true'}},
            {'name': 'mcp:translate', 'protocol': 'openid-connect',
             'attributes': {'include.in.token.scope': 'true'}},
        ],
        'clients': [
            {'clientId': 'mcp-demo', 'publicClient': True,
             'standardFlowEnabled': True, 'directAccessGrantsEnabled': False,
             'consentRequired': True,
             'redirectUris': [PUBLIC + '/callback'],
             'attributes': {
                 'pkce.code.challenge.method': 'S256',
                 'post.logout.redirect.uris': PUBLIC + '/',
             },
             'defaultClientScopes': [],
             'optionalClientScopes': ['mcp:tools', 'mcp:translate'],
             'protocolMappers': [{
                 'name': 'MCP audience', 'protocol': 'openid-connect',
                 'protocolMapper': 'oidc-audience-mapper',
                 'config': {'included.custom.audience': PUBLIC + '/mcp',
                            'access.token.claim': 'true',
                            'id.token.claim': 'false'},
             }, {
                 'name': 'Subject', 'protocol': 'openid-connect',
                 'protocolMapper': 'oidc-usermodel-property-mapper',
                 'config': {'user.attribute': 'id', 'claim.name': 'sub',
                            'jsonType.label': 'String',
                            'access.token.claim': 'true',
                            'id.token.claim': 'true'},
             }]},
            {'clientId': 'mcp-edge', 'bearerOnly': True,
             'attributes': {'resource_url': PUBLIC + '/mcp'}},
        ],
    }
    write('realm.json', json.dumps(realm))
    write('protected-resource.json', json.dumps({
        'resource': PUBLIC + '/mcp',
        'authorization_servers': [PUBLIC + '/idp/realms/mcp'],
        'scopes_supported': ['mcp:tools'],
        'bearer_methods_supported': ['header'],
    }))


def configure():
    host_state = os.environ['OAUTH_STATE_DIR']
    example = os.environ['OAUTH_HOST_EXAMPLE']
    modules = os.environ.get('NGINX_MODULES', '')
    otel = os.environ.get('NGINX_OTEL_MODULE', '')
    if otel:
        modules += '\nload_module "' + otel + '";'
    replacements = {
        'MODULES': modules, 'STATE': host_state, 'EXAMPLE': example,
        'LICENSE': os.environ['NGINX_LICENSE'],
        'PORT': os.environ['DEMO_PORT'], 'HOST': URL.netloc,
        'PUBLIC_PORT': str(URL.port or 443),
        'APP': os.environ['OAUTH_APP_ADDRESS'],
        'IDP': os.environ['OAUTH_IDP_ADDRESS'],
        'BACKEND': os.environ['OAUTH_BACKEND_ADDRESS'],
    }
    template = Path('/example/nginx.conf').read_text()
    for name, value in replacements.items():
        if any(c in value for c in '\r\n') and name != 'MODULES':
            raise ValueError('Unexpected newline in configuration parameter')
        template = template.replace('@' + name + '@', value)
    write('nginx.conf', template)
    constants = '\n'.join(
        'map $host $%s { default "%s"; }' % (name, value)
        for name, value in {
            'mcp_issuer': PUBLIC + '/idp/realms/mcp',
            'mcp_resource': PUBLIC + '/mcp',
            'mcp_metadata_url': PUBLIC
                + '/.well-known/oauth-protected-resource/mcp',
        }.items())
    if otel:
        telemetry = ('otel_service_name nginx-mcp-edge;\notel_exporter { '
                     'endpoint ' + os.environ['OAUTH_OTEL_ADDRESS'] + '; }\n')
        tracing = ('otel_trace on;\notel_trace_context inject;\n'
                   'otel_span_name "MCP gateway $mcp_body_tool";\n'
                   'otel_span_attr "mcp.gateway.reason" $mcp_oauth_reason;\n'
                   'otel_span_attr "mcp.tool.name" $mcp_body_tool;\n')
    else:
        telemetry = ('map $host $otel_trace_id { default ""; }\n'
                     'map $host $otel_span_id { default ""; }\n')
        tracing = ''
    write('telemetry.conf', constants + '\n' + telemetry)
    write('tracing.conf', tracing)


def ready():
    host = 'https://host.docker.internal:' + os.environ['DEMO_PORT']
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        try:
            response = requests.get(
                host + '/idp/realms/mcp/.well-known/openid-configuration',
                headers={'Host': URL.netloc}, verify='/state/certs/ca.crt',
                timeout=3)
            if response.status_code == 200:
                return
        except requests.RequestException:
            pass
        time.sleep(1)
    raise ValueError('IdP did not become ready')


if __name__ == '__main__':
    {'prepare': prepare, 'configure': configure, 'ready': ready}[sys.argv[1]]()
    if os.getuid() == 0:
        for path in [STATE, *STATE.rglob('*')]:
            os.chown(path, int(os.environ['OAUTH_UID']),
                     int(os.environ['OAUTH_GID']))
