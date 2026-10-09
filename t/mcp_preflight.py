#!/usr/bin/env python3
# Copyright (C) Dmitry Volyntsev
# Copyright (C) F5, Inc.

import argparse
import os
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--plus', required=True)
    parser.add_argument('--license', required=True)
    parser.add_argument('--dynamic', required=True)
    parser.add_argument('--njs-module', required=True)
    parser.add_argument('--otel-module', required=True)
    parser.add_argument('--oss', required=True)
    parser.add_argument('--no-json', required=True)
    parser.add_argument('--no-ssl', required=True)
    parser.add_argument('--no-jwt', required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    preflight = root / 'demo/oauth-resource-protection/preflight.sh'
    env = dict(os.environ, NGINX_LICENSE=args.license,
               NGINX_MODULES='', NGINX_OTEL_MODULE='')

    def check(name, binary, failures=(), modules='', otel=''):
        result = subprocess.run(
            ['sh', str(preflight)],
            env=dict(env, NGINX_BINARY=binary, NGINX_MODULES=modules,
                     NGINX_OTEL_MODULE=otel),
            capture_output=True, text=True, timeout=120)
        output = result.stdout + result.stderr
        assert result.returncode == (1 if failures else 0), output
        for failure in failures:
            assert 'FAIL ' + failure in output, output
        if not failures:
            assert 'NGINX preflight passed.' in output, output
        assert 'Segmentation fault' not in output, output
        assert 'Sanitizer' not in output, output
        print('PASS', name)
        return output

    check('static njs + dynamic OTel', args.plus, otel=args.otel_module)
    check('static njs without optional OTel', args.plus)
    njs = 'load_module "' + args.njs_module + '";'
    check('dynamic njs', args.dynamic, modules=njs)
    check('nginx-se without loaded njs', args.dynamic,
          ('njs:', 'njs QuickJS engine:'))
    check('missing njs module', args.dynamic, ('binary/module loading:',),
          modules='load_module "/nonexistent/mcp-njs.so";')
    check('missing OTel, njs present', args.dynamic,
          ('binary/module loading:',), modules=njs,
          otel='/nonexistent/mcp-otel.so')
    check('missing njs, OTel present', args.plus,
          ('binary/module loading:',), otel=args.otel_module,
          modules='load_module "/nonexistent/mcp-njs.so";')
    check('nginx-se without JSON', args.no_json,
          ('HTTP JSON:', 'njs:', 'njs QuickJS engine:'))
    check('nginx-se without SSL', args.no_ssl,
          ('HTTP SSL:', 'njs:', 'njs QuickJS engine:'))
    check('nginx-se without JWT', args.no_jwt,
          ('JWT authentication:', 'njs:', 'njs QuickJS engine:'))
    check('OSS', args.oss, ('JWT authentication:',
                          'post-auth internal redirect:',
                          'license management directives:'))
    # Module built for nginx-se must fail when attached to a different ABI.
    check('incompatible njs module on OSS', args.oss,
          ('binary/module loading:',), modules=njs)
    runner = root / 'demo/oauth-resource-protection/run.sh'
    result = subprocess.run(
        [str(runner), 'up'],
        env=dict(env, NGINX_BINARY=args.dynamic),
        capture_output=True, text=True, timeout=120)
    output = result.stdout + result.stderr
    assert result.returncode == 1, output
    assert 'no demo containers started' in output, output
    assert 'Building' not in output and 'Creating' not in output, output
    print('PASS runner up fails before Docker startup')


if __name__ == '__main__':
    main()
