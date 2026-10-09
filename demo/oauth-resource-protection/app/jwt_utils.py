# Copyright (C) Dmitry Volyntsev
# Copyright (C) F5, Inc.

import base64
import json
import time

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding


def encode(value):
    return base64.urlsafe_b64encode(value).rstrip(b'=').decode()


def jwk(key):
    numbers = key.public_key().public_numbers()
    integer = lambda n: encode(n.to_bytes((n.bit_length() + 7) // 8, 'big'))
    return {'kty': 'RSA', 'kid': 'demo-fixture', 'alg': 'RS256',
            'use': 'sig', 'n': integer(numbers.n), 'e': integer(numbers.e)}


def token(key, public, **overrides):
    now = int(time.time())
    claims = {'iss': public + '/idp/realms/mcp', 'aud': public + '/mcp',
              'sub': 'fixture-alice', 'tenant': 'research', 'typ': 'Bearer',
              'scope': 'mcp:tools', 'iat': now, 'exp': now + 300}
    claims.update(overrides)
    header = {'alg': 'RS256', 'typ': 'JWT', 'kid': 'demo-fixture'}
    data = '.'.join(encode(json.dumps(v).encode()) for v in (header, claims))
    signature = key.sign(data.encode(), padding.PKCS1v15(), hashes.SHA256())
    return data + '.' + encode(signature)
