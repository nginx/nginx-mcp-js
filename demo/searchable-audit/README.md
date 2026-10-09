# MCP searchable gateway audit

Search [MCP] tool calls and gateway decisions in a structured audit journal.

## NGINX

Extracts MCP metadata with [`json_set`][json-set] and writes events using
[`log_format escape=json`][log-format] and [`access_log`][access-log].
An [njs] response filter adds MCP outcomes. Configure event generation in
the
[NGINX configuration](../structured-audit/nginx.conf) and file output in
the [audit log destinations](audit-logs.conf).

## Demo environment

The [OTel Collector][collector] sends events to [Loki], a log storage and
query system. [Grafana] provides readable summaries and filters; mock
[Go SDK][go-sdk] traffic and checker links illustrate investigation of
individual calls.

## Run and investigate

From demo/:

```sh
./run.sh searchable-audit
python3 searchable-audit/check.py
```

Open Grafana at http://127.0.0.1:3000 (admin/admin), dashboard
**MCP searchable audit**. The checker prints links to three specific
events: success, RPC error inside HTTP 200, and header/body mismatch.
For a custom Grafana port, pass `--grafana http://127.0.0.1:8001`.

Try these investigations:

1. Select **MCP outcome = rpc_error**. HTTP 200 calls can still fail.
2. Reset outcome to All and select **Gateway decision = rejected**.
   The summary explains why NGINX stopped each request.
3. Reset filters to All and paste a checker **Request ID**. Expand its
   full JSON event to compare header/body tool names and see whether an
   upstream connection was attempted.

The background generator keeps the journal active. For a quiet view:

```sh
./run.sh searchable-audit stop mcp-client
python3 searchable-audit/check.py
```

Stop with `./run.sh searchable-audit down` before switching demos.

## Collection

NGINX writes JSON to a shared file. The OTel Collector tails it with a
persistent checkpoint and sends events to Loki over OTLP. Only service
name is an indexed label; tool, decision and request IDs are searchable
structured metadata. The source event format is described in the
[terminal audit demo](../structured-audit/README.md).

Source logs, checkpoints and Loki data survive `down` in Docker volumes.
This short-lived demo does not rotate the source file. Trace IDs remain
in events; trace storage and navigation are a separate demo.

[MCP]: https://modelcontextprotocol.io/specification/2026-07-28
[json-set]: https://nginx.org/en/docs/http/ngx_http_json_module.html#json_set
[log-format]: https://nginx.org/en/docs/http/ngx_http_log_module.html#log_format
[access-log]: https://nginx.org/en/docs/http/ngx_http_log_module.html#access_log
[njs]: https://nginx.org/en/docs/njs/
[go-sdk]: https://pkg.go.dev/github.com/modelcontextprotocol/go-sdk@v1.7.0/mcp
[collector]: https://opentelemetry.io/docs/collector/
[Loki]: https://grafana.com/docs/loki/latest/
[Grafana]: https://grafana.com/docs/grafana/latest/
