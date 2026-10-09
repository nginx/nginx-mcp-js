#!/bin/sh
# Copyright (C) Dmitry Volyntsev
# Copyright (C) F5, Inc.

set -eu

example=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
demo=$(dirname "$example")
if [ -f "$demo/.env" ]; then
    # Match Compose: the caller's environment overrides the dotenv defaults.
    while IFS= read -r line || [ -n "$line" ]; do
        case "$line" in
            ''|'#'*) continue ;;
            *=*)
                name=${line%%=*}
                value=${line#*=}
                case "$name" in
                    *[!A-Za-z0-9_]*|'') continue ;;
                esac
                if ! printenv "$name" >/dev/null; then
                    export "$name=$value"
                fi
                ;;
        esac
    done < "$demo/.env"
fi

export DEMO_PORT=${DEMO_PORT:-4096}
export DEMO_PUBLIC_URL=${DEMO_PUBLIC_URL:-https://localhost:$DEMO_PORT}
export GRAFANA_PORT=${GRAFANA_PORT:-8001}
export GRAFANA_PUBLIC_URL=${GRAFANA_PUBLIC_URL:-http://localhost:$GRAFANA_PORT}
export OAUTH_STATE_DIR=${OAUTH_STATE_DIR:-$example/.state}
export OAUTH_HOST_EXAMPLE=$example
export OAUTH_UID=$(id -u)
export OAUTH_GID=$(id -g)

compose() {
    docker compose --project-name mcp-oauth \
        --project-directory "$demo" -f "$example/compose.yaml" "$@"
}

nginx() {
    "$NGINX_BINARY" -p "$OAUTH_STATE_DIR/" \
        -c "$OAUTH_STATE_DIR/nginx.conf" "$@"
}

case ${1:-up} in
    up)
        sh "$example/preflight.sh"
        mkdir -p "$OAUTH_STATE_DIR/logs" "$OAUTH_STATE_DIR/certs"
        if [ -f "$OAUTH_STATE_DIR/nginx.pid" ]; then
            printf '%s\n' 'Already running; use down before up.' >&2
            exit 1
        fi
        cleanup() {
            code=$?
            if [ "$code" -ne 0 ]; then
                compose logs --tail=30 >&2 || true
                if [ -f "$OAUTH_STATE_DIR/nginx.pid" ]; then
                    nginx -s quit || true
                fi
                compose down || true
            fi
            exit "$code"
        }
        trap cleanup EXIT
        compose build app mcp-information
        compose run --rm --no-deps --user 0:0 \
            -e NGINX_LICENSE -e NGINX_MODULES -e NGINX_OTEL_MODULE \
            app python bootstrap.py prepare
        compose up -d idp mcp-information otel-collector audit-loki \
            audit-tempo grafana app
        export OAUTH_APP_ADDRESS=$(compose port app 8080)
        export OAUTH_IDP_ADDRESS=$(compose port idp 8080)
        export OAUTH_BACKEND_ADDRESS=$(compose port mcp-information 9001)
        export OAUTH_OTEL_ADDRESS=$(compose port otel-collector 4317)
        compose run --rm --no-deps --user 0:0 \
            -e NGINX_LICENSE -e NGINX_MODULES -e NGINX_OTEL_MODULE \
            -e OAUTH_IDP_ADDRESS -e OAUTH_BACKEND_ADDRESS \
            -e OAUTH_OTEL_ADDRESS -e OAUTH_APP_ADDRESS \
            app python bootstrap.py configure
        nginx -t
        nginx
        if ! compose exec -T app python bootstrap.py ready; then
            nginx -s quit
            exit 1
        fi
        printf 'Demo: %s\nGrafana: %s\nCA: %s\n' \
            "$DEMO_PUBLIC_URL" "$GRAFANA_PUBLIC_URL" \
            "$OAUTH_STATE_DIR/certs/ca.crt"
        trap - EXIT
        ;;
    down)
        if [ -f "$OAUTH_STATE_DIR/nginx.pid" ]; then
            IFS= read -r pid < "$OAUTH_STATE_DIR/nginx.pid"
            case "$pid" in
                ''|*[!0-9]*|0|1)
                    printf '%s\n' 'Invalid demo NGINX PID.' >&2
                    exit 1
                    ;;
            esac
            if kill -0 "$pid" 2>/dev/null; then
                kill -QUIT "$pid"
                remaining=30
                while kill -0 "$pid" 2>/dev/null; do
                    if [ "$remaining" -eq 0 ]; then
                        printf '%s\n' \
                            'NGINX is still shutting down; retry down.' >&2
                        exit 1
                    fi
                    sleep 1
                    remaining=$((remaining - 1))
                done
            fi
        fi
        compose down
        ;;
    preflight)
        sh "$example/preflight.sh"
        ;;
    login|logout|idp-logout|scenario|check)
        compose exec -T app python cli.py "$@"
        ;;
    check-flow)
        docker run --rm --network host --user "$OAUTH_UID:$OAUTH_GID" \
            -v "$OAUTH_STATE_DIR:/state" mcp-oauth-app:2026-07-28 \
            python check.py
        ;;
    logs)
        compose logs --tail=100
        ;;
    *)
        printf '%s\n' \
            'Usage: run.sh [up|down|preflight|login|logout|idp-logout|' \
            '               scenario NAME|' \
            '               check|check-flow|logs]' >&2
        exit 1
        ;;
esac
