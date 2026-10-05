# Native MCP routing and HTTP observability

Route [MCP] calls by tool and observe their HTTP status and latency.

## NGINX

Reads request bodies early with [`client_body_early_read`][early-read]
and extracts MCP metadata with [`json_set`][json-set]. Header/body checks
validate routing metadata; [`map`][map] selects the backend and the
[OTel module][nginx-otel] exports HTTP telemetry.
Configure tool routes, upstreams and span attributes in the
[NGINX configuration](nginx.conf) and its includes.

## Demo environment

Mock backends built with the [Go SDK][go-sdk] and mixed traffic exercise
routing and rejection paths. The [OTel Collector][collector] converts
gateway spans to metrics; [Prometheus] and [Grafana] show HTTP status and
latency by tool and backend.

## Run

From demo/:

```sh
./run.sh native-routing
./run.sh native-routing exec nginx nginx -t
python3 shared/scenarios/check.py --prometheus http://127.0.0.1:9090
```

Grafana: `MCP native HTTP edge`. Local ports and load settings are
described in [the demo guide](../README.md).

## Architecture

```text
client -> NGINX /mcp -> information / operations / data Go backends
             |
             +-> OTel Collector -> Prometheus -> Grafana
```

The body limit and buffer are both 64 KiB. HTTP method/media-type checks,
protocol version and header/body comparisons precede upstream selection.
Tools outside the allowlist receive 403; unsupported RPC methods 404;
GET/DELETE 405 with `Allow: POST`. Fixed JSON-RPC rejection bodies use
`id: null`; HTTP policy errors use simple JSON bodies.

## What to observe

Mixed traffic produces HTTP 400/403 and semantic errors under HTTP 200.
This dashboard counts HTTP requests, latency and HTTP status by known tool
and backend. It intentionally cannot distinguish tool/RPC errors from
successful results within HTTP 200. Raw client names are not metric labels.
Early 413 rejections before location selection are access-log events, not
nginx-otel spans.

Only direct already-known tools/call requests are supported. This is not
a catalog or discovery server. See the root README for protocol scope.

[MCP]: https://modelcontextprotocol.io/specification/2026-07-28
[early-read]: https://nginx.org/en/docs/http/ngx_http_core_module.html#client_body_early_read
[json-set]: https://nginx.org/en/docs/http/ngx_http_json_module.html#json_set
[map]: https://nginx.org/en/docs/http/ngx_http_map_module.html#map
[nginx-otel]: https://nginx.org/en/docs/ngx_otel_module.html
[go-sdk]: https://pkg.go.dev/github.com/modelcontextprotocol/go-sdk@v1.7.0/mcp
[collector]: https://opentelemetry.io/docs/collector/
[Prometheus]: https://prometheus.io/docs/introduction/overview/
[Grafana]: https://grafana.com/docs/grafana/latest/
