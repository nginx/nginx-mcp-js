# Per-tool rate limits with NGINX OSS

NGINX limits calls to one tool while another tool on the same [MCP] server
remains available. Rejected calls receive HTTP 429 before reaching upstream.

## NGINX

Uses the validated tool name as the key for
[`limit_req_zone`][limit-zone]. [`limit_req`][limit] applies independent
tool limits shared across workers. Configure the zone rate and burst in
the [NGINX configuration](nginx.conf) and
[limit settings](limits.conf).

## Demo environment

Two traffic streams call the same mock [Go SDK][go-sdk] backend at
different rates. The [OTel Collector][collector], [Prometheus] and
[Grafana] show which calls NGINX forwards or rejects, making per-tool
isolation visible.

## Run

From demo/, after stopping the previous example:

```sh
./run.sh tool-rate-limiting
python3 tool-rate-limiting/check.py
```

Open the `MCP tool rate limits` dashboard in Grafana. It shows requests
forwarded to the MCP server and requests rejected by NGINX.

The checker briefly stops the traffic generators, verifies independent
tool buckets and recovery, then restarts traffic.

[MCP]: https://modelcontextprotocol.io/specification/2026-07-28
[limit-zone]: https://nginx.org/en/docs/http/ngx_http_limit_req_module.html#limit_req_zone
[limit]: https://nginx.org/en/docs/http/ngx_http_limit_req_module.html#limit_req
[go-sdk]: https://pkg.go.dev/github.com/modelcontextprotocol/go-sdk@v1.7.0/mcp
[collector]: https://opentelemetry.io/docs/collector/
[Prometheus]: https://prometheus.io/docs/introduction/overview/
[Grafana]: https://grafana.com/docs/grafana/latest/
