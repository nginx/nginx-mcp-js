#!/bin/sh
# Copyright (C) Dmitry Volyntsev
# Copyright (C) F5, Inc.

set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
mode=${1:-native-routing}
if [ "$#" -gt 0 ]; then
    shift
fi

case "$mode" in
    native-routing|server-observability|njs-response-observability|\
    njs-response-observability-python) ;;
    *)
        printf '%s\n' \
            "Usage: $0 <example> [compose command...]" \
            "Examples: native-routing, server-observability," \
            "          njs-response-observability," \
            "          njs-response-observability-python" >&2
        exit 1
        ;;
esac

if [ "$#" -eq 0 ]; then
    set -- up -d --build --force-recreate
fi

if [ "$mode" = server-observability ] || \
   [ "$mode" = njs-response-observability-python ]; then
    if [ "$1" = up ]; then
        docker compose --project-directory "$script_dir" \
            -f "$script_dir/shared/compose.yaml" build mcp-information
    fi
    example=$mode
    if [ "$mode" = njs-response-observability-python ]; then
        example=njs-response-observability
    fi
    set -- -f "$script_dir/shared/python.yaml" \
        -f "$script_dir/$example/compose.yaml" "$@"
else
    set -- -f "$script_dir/$mode/compose.yaml" "$@"
fi

exec docker compose --project-directory "$script_dir" \
    -f "$script_dir/shared/compose.yaml" "$@"
