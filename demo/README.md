# Runnable MCP examples

Choose an example from [the root catalog](../README.md#demo-catalog).
You need Docker with Compose 2.24+ and Python 3 for the scenario checker.

## Start and stop

Run from this directory:

```sh
./run.sh native-routing
```

This builds and starts NGINX, mock tool backends, monitoring services and
mixed success/error traffic. Open Grafana at http://127.0.0.1:3000
(admin/admin) and select `MCP native HTTP edge`.

Stop the current example before switching:

```sh
./run.sh native-routing down
./run.sh server-observability
```

Use the same example name for subsequent Compose commands, including
`down`, `ps` and `logs --tail=30 mcp-client`.

## Local settings

Create an ignored `.env` for deployment-specific settings:

```dotenv
GRAFANA_PORT=8001
MCP_LOAD_RPS=40
MCP_LOAD_DURATION=24h
```

Defaults: MCP http://127.0.0.1:9000/mcp, Grafana
http://127.0.0.1:3000 (admin/admin), Prometheus http://127.0.0.1:9090.
Override `MCP_PORT`, `GRAFANA_PORT` and `PROMETHEUS_PORT` as needed.
For isolated deployments set `COMPOSE_PROJECT_NAME`.

## Shared traffic and backends

Go SDK v1.7.0 servers provide information, operations and data tool groups.
Server-side observation replaces information with Python MCP SDK 2.3.0.
`shared/routes.conf` and `shared/upstreams.conf` contain the concrete
allowlist and Docker addresses; reusable processing lives in ../nginx/.

The generator caps aggregate traffic at 40 requests/s, repeating a
100-request cycle per worker: 70% success, 10% tool error, 5% RPC error,
5% header mismatch (400), 5% policy denial (403), 5% input-required.
It runs for 24 hours and restarts until explicitly stopped.

Configure `MCP_TOOL_ERROR_PERCENT`, `MCP_RPC_ERROR_PERCENT`,
`MCP_HEADER_ERROR_PERCENT`, `MCP_POLICY_DENIAL_PERCENT` and
`MCP_INPUT_REQUIRED_PERCENT` in `.env`. Values must sum to at most 100;
the remainder is success. Set all to zero for success-only traffic.
Stop load with `./run.sh <example> stop mcp-client`.

## Verification

```sh
python3 shared/scenarios/check.py --prometheus http://127.0.0.1:9090
python3 shared/scenarios/check.py --mixed --prometheus http://127.0.0.1:9090
```

The first command sends deterministic calls and verifies routing and
rejections. The second checks that background mixed traffic produces
nonzero error rates. Allow 30-60 seconds for rate windows to fill.

Servers enable demo-only simulation. `arguments.simulate` selects success,
tool_error, rpc_error, input_required, or large_response. These outcomes
use the ordinary tools and do not add special public routes.

## Deployment layout

The launcher merges `shared/compose.yaml` with backend and example
overlays. Paths are relative to demo/. It builds the Go image shared by
the client and Go backends before starting Python modes.

`shared/http.conf`, `mcp-server.conf` and `mcp-proxy.conf` assemble the
reusable NGINX snippets. Routes, Docker addresses, collector endpoints and
Grafana provisioning are deployment settings, separate from the reusable
artifacts in the repository root. Additional policy, audit or trace
storage recipes can use this same assembly and add Compose overlays.

The routing regression test uses the official NGINX image and the
`nginx-tests` Perl harness. With an nginx-tests checkout available:

```sh
docker build -t mcp-routing-test -f ../t/Dockerfile ..
timeout 60s docker run --rm --memory=768m --memory-swap=768m \
    -v "$(pwd)/..:/workspace:ro" \
    -v "/path/to/nginx-tests:/nginx-tests:ro" mcp-routing-test
```

CI runs the three main demos and checks routing, metrics and Grafana
provisioning. The Perl regression tests are available for local checks.
