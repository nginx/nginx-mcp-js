# MCP audit and traces

Find an [MCP] tool call in the audit journal, then follow its trace through
NGINX and the backend.

## NGINX

The [OTel module][nginx-otel] creates gateway spans with MCP attributes and
injects [W3C trace context][trace-context] into upstream requests using
[`otel_trace_context`][otel-context]. Audit events include the
corresponding trace IDs. Configure context injection
and span names in the [tracing configuration](tracing.conf), loaded by
the [NGINX configuration](../structured-audit/nginx.conf).

## Demo environment

Instrumented [Go SDK][go-sdk] backends add HTTP and tool-execution spans.
The [OTel Collector][collector] sends traces to [Tempo], a distributed
trace store. [Grafana] links [Loki] audit events to the execution
chain so readers can inspect timing and tool errors.

## Run and follow a call

From demo/:

```sh
./run.sh audit-traces
python3 audit-traces/check.py
```

Open Grafana at http://127.0.0.1:3000 (admin/admin), dashboard
**MCP searchable audit**. For a custom port, pass
`--grafana http://127.0.0.1:8001` to the checker.

The checker prints links to three audit events. Expand each event and
click **View trace**:

1. **Success**: NGINX gateway, backend HTTP and `tools/call` spans form
   one chain. The tool span accounts for backend processing time.
2. **RPC error inside HTTP 200**: HTTP succeeded, but the tool span shows
   the error and its message. Compare it with the audit outcome.
3. **Header/body mismatch**: only the gateway span exists. NGINX rejected
   the call before it reached the backend.

In the trace view, use **Logs for this span** to return to the correlated
gateway event. The background generator keeps the journal active; stop
it with `./run.sh audit-traces stop mcp-client` for a quiet investigation.

Stop with `./run.sh audit-traces down` before switching demos.

## Trace scope

Backend tracing is enabled only in this demo. These mock tools have no
downstream services, so the trace ends at tool execution.

Audit events carry trace IDs independently of trace storage. Early
rejections may have no span. This demo exports all generated spans and
keeps Tempo data in a local volume with 24-hour block retention. Production
sampling and storage policy are deployment choices.

[MCP]: https://modelcontextprotocol.io/specification/2026-07-28
[nginx-otel]: https://nginx.org/en/docs/ngx_otel_module.html
[trace-context]: https://www.w3.org/TR/trace-context/
[otel-context]: https://nginx.org/en/docs/ngx_otel_module.html#otel_trace_context
[go-sdk]: https://pkg.go.dev/github.com/modelcontextprotocol/go-sdk@v1.7.0/mcp
[collector]: https://opentelemetry.io/docs/collector/
[Tempo]: https://grafana.com/docs/tempo/latest/
[Grafana]: https://grafana.com/docs/grafana/latest/
[Loki]: https://grafana.com/docs/loki/latest/
