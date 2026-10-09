# Per-tool circuit breaker with NGINX OSS and njs

NGINX temporarily blocks a failing tool while another tool on the same
[MCP] server remains available. Calls resume automatically after cooldown.

## NGINX

An [njs] response observer identifies failures;
[`js_shared_dict_zone`][shared-zone] provides dictionaries for per-tool
failure counters and cooldown state across workers. An admission check
using [`js_set`][js-set] rejects blocked calls before proxying.
Configure the shared zones and checks in the
[NGINX configuration](nginx.conf); the
[njs policy](../../njs/mcp-breaker.mjs) defines threshold and cooldown.

## Demo environment

A mock [Go SDK][go-sdk] backend alternates failures and recovery while
another tool stays healthy. The [OTel Collector][collector], [Prometheus]
and [Grafana] show errors, NGINX blocks and resumed calls on one timeline.

## Run

From demo/, after stopping the previous example:

```sh
./run.sh tool-circuit-breaking
python3 tool-circuit-breaking/check.py
```

Open `MCP tool circuit breaker` in Grafana. One graph shows successful
calls, server errors and NGINX blocks on the same timeline and scale.

This example uses a small fixed-window failure counter and a cooldown,
shared across workers. It counts internal RPC errors and selected upstream
HTTP failures, not business tool errors or input-required results. It does
not coordinate half-open probes: traffic resumes when the cooldown expires.

[MCP]: https://modelcontextprotocol.io/specification/2026-07-28
[njs]: https://nginx.org/en/docs/njs/
[shared-zone]: https://nginx.org/en/docs/http/ngx_http_js_module.html#js_shared_dict_zone
[js-set]: https://nginx.org/en/docs/http/ngx_http_js_module.html#js_set
[go-sdk]: https://pkg.go.dev/github.com/modelcontextprotocol/go-sdk@v1.7.0/mcp
[collector]: https://opentelemetry.io/docs/collector/
[Prometheus]: https://prometheus.io/docs/introduction/overview/
[Grafana]: https://grafana.com/docs/grafana/latest/
