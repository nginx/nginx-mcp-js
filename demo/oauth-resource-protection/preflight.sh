#!/bin/sh
# Copyright (C) Dmitry Volyntsev
# Copyright (C) F5, Inc.

set -eu

failed=0
report() {
    printf '  FAIL %s\n' "$1" >&2
    failed=1
}

if [ -z "${NGINX_BINARY:-}" ] || [ ! -x "$NGINX_BINARY" ]; then
    printf '%s\n' 'Set NGINX_BINARY to an executable NGINX binary.' >&2
    exit 1
fi
if [ -z "${NGINX_LICENSE:-}" ] || [ ! -r "$NGINX_LICENSE" ]; then
    report 'license: set NGINX_LICENSE to a readable license JWT'
fi

probe_dir=$(mktemp -d "${TMPDIR:-/tmp}/mcp-preflight.XXXXXXXX")
trap 'rm -rf "$probe_dir"' EXIT
mkdir "$probe_dir/logs"
printf '%s\n' 'export default {value: () => "1", filter: () => {}};' \
    > "$probe_dir/probe.mjs"
modules=${NGINX_MODULES:-}
management=""
if [ -n "${NGINX_OTEL_MODULE:-}" ]; then
    modules="$modules
load_module \"$NGINX_OTEL_MODULE\";"
fi

probe() {
    printf '%s\n' "$modules" "$management" \
        'error_log stderr;' 'events {}' "$1" \
        > "$probe_dir/nginx.conf"
    if timeout 10s "$NGINX_BINARY" -p "$probe_dir/" \
        -c "$probe_dir/nginx.conf" -t > "$probe_dir/output" 2>&1; then
        return 0
    fi
    return 1
}

diagnostic() {
    while IFS= read -r line; do
        printf '    %s\n' "$line" >&2
    done < "$probe_dir/output"
}

check() {
    if probe "$2"; then
        printf '  PASS %s\n' "$1"
    else
        report "$1: $3"
        diagnostic
    fi
}

printf 'NGINX preflight: %s\n' "$NGINX_BINARY"
if ! probe 'http {}'; then
    output=""
    while IFS= read -r line; do
        output="$output $line"
    done < "$probe_dir/output"
    case "$output" in
        *'License file is required'*)
            if [ -z "${NGINX_LICENSE:-}" ] || [ ! -r "$NGINX_LICENSE" ]; then
                diagnostic
                exit 1
            fi
            management="mgmt { license_token \"$NGINX_LICENSE\";
                usage_report endpoint=127.1.1.121;
                enforce_initial_report off; }"
            ;;
        *)
            report 'binary/module loading: check paths, dependencies and ABI'
            diagnostic
            exit 1
            ;;
    esac
    if ! probe 'http {}'; then
        report 'license management: cannot load the configured license'
        diagnostic
        exit 1
    fi
fi
printf '%s\n' '  PASS binary and configured module loading'

check 'HTTP SSL' \
    'http { ssl_protocols TLSv1.2 TLSv1.3; }' \
    'build with --with-http_ssl_module'
check 'JWT authentication' \
    'http { map $host $probe_valid { default 1; }
        server { location / { auth_jwt "MCP";
            auth_jwt_key_request /keys; auth_jwt_key_cache 30s;
            auth_jwt_require $probe_valid; } } }' \
    'requires NGINX Plus JWT support (--with-http_auth_jwt_module)'
check 'post-auth internal redirect' \
    'http { server { location / { internal_redirect @authenticated; }
        location @authenticated { return 204; } } }' \
    'requires NGINX Plus internal_redirect support'
check 'HTTP JSON' \
    'http { json_set $probe_method $request_body method; }' \
    'build with --with-http_json_module'
check 'early request body reading' \
    'http { server { client_body_early_read on; } }' \
    'requires a recent NGINX build with client_body_early_read'
check 'njs' \
    "http { js_import probe from \"$probe_dir/probe.mjs\";
        js_var \$probe_value; js_set \$probe_check probe.value;
        server { location / { js_header_filter probe.filter;
            js_body_filter probe.filter buffer_type=buffer; } } }" \
    'build njs in or load ngx_http_js_module.so through NGINX_MODULES'
check 'njs QuickJS engine' \
    'http { js_engine qjs; }' \
    'load an njs module built with QuickJS support'
if [ -n "${NGINX_LICENSE:-}" ] && [ -r "$NGINX_LICENSE" ]; then
    saved_management=$management
    management=""
    check 'license management directives' \
        "mgmt { license_token \"$NGINX_LICENSE\";
            usage_report endpoint=127.1.1.121; enforce_initial_report off; }
         http {}" \
        'requires a licensed Plus/nginx-se build with management support'
    management=$saved_management
fi
if [ -n "${NGINX_OTEL_MODULE:-}" ]; then
    check 'OpenTelemetry' \
        'http { otel_service_name mcp-preflight;
            otel_exporter { endpoint 127.0.0.1:4317; }
            server { otel_trace on; otel_trace_context inject;
                otel_span_attr "mcp.tool.name" "probe"; } }' \
        'set NGINX_OTEL_MODULE to a compatible ngx_otel_module.so'
else
    printf '%s\n' '  INFO OpenTelemetry disabled (NGINX_OTEL_MODULE unset)'
fi
if [ "$failed" -ne 0 ]; then
    printf '%s\n' 'NGINX preflight failed; no demo containers started.' >&2
    exit 1
fi
printf '%s\n' 'NGINX preflight passed.'
