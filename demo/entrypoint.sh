#!/bin/sh
# Copyright (c) F5, Inc.
#
# This source code is licensed under the Apache License, Version 2.0 license found in the
# LICENSE file in the root directory of this source tree.

set -e

echo "Starting OTel Collector..."
otelcol-contrib --config /etc/otel/config.yaml &

echo "Starting Prometheus..."
prometheus \
    --config.file=/etc/prometheus/prometheus.yaml \
    --storage.tsdb.path=/tmp/prometheus \
    --web.listen-address=:9090 &

echo "Starting Grafana on :8001..."
/opt/grafana/bin/grafana-server \
    --homepath=/opt/grafana \
    --config=/opt/grafana/conf/defaults.ini \
    cfg:server.http_port=8001 \
    cfg:paths.provisioning=/etc/grafana/provisioning \
    cfg:paths.data=/tmp/grafana \
    cfg:paths.logs=/tmp/grafana/log \
    cfg:security.admin_password=admin \
    cfg:auth.disable_login_form=false &

echo "Starting MCP Servers..."
mcp_server --name mcp-stable --port 9001 \
    --error-rate 0 --tool-error-rate 0 --long-rate 0 &
mcp_server --name mcp-flaky --port 9002 \
    --error-rate 0.02 --tool-error-rate 0.10 --long-rate 0 &
mcp_server --name mcp-sluggish --port 9003 \
    --error-rate 0 --tool-error-rate 0 \
    --max-latency 100ms &

echo "Starting nginx..."
nginx -c /etc/nginx/nginx.conf

sleep 2

echo "Starting MCP Client (traffic generator)..."
exec mcp_client \
    -url http://127.0.0.1:9000 \
    -duration 2h \
    -workers 6
