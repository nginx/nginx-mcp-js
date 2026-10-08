# MCP telemetry processing and dashboards

`otel/edge.yaml` contains a Collector spanmetrics pipeline for NGINX HTTP
spans. Supply an `otlp` receiver and `prometheus` exporter separately; the
demo uses demo/shared/otel.yaml and loads both YAML files with `--config`.

The filter selects resource `service.name=nginx-mcp-edge`. Change it for
your deployment together with `otel_service_name`. Dimensions are known
tool, backend and HTTP status; raw client names are not metric labels.
Metric namespace `edge` distinguishes HTTP counts from MCP execution.

`grafana/http/mcp-http.json` visualizes `edge_calls_total` and latency.
It expects a Prometheus datasource with UID `prometheus`; provisioning
and endpoints are deployment-specific and reside in demo/shared/grafana/.

HTTP 200 is not semantic MCP success. These panels report HTTP outcomes.
Early NGINX rejections before location selection may have no OTel span.

`otel/sdk.yaml` adds a separate `mcp_exec` spanmetrics connector and pipeline
for semantic SDK operations. Load it alongside edge.yaml and deployment
receivers/exporters. Its filter selects Python SDK tools/call spans;
adapt service names for your deployment. Do not combine HTTP and MCP
operation counters into one request total.

This example exports operations for only the Python information backend.
The SDK directory and pipeline names identify the instrumentation source;
they do not imply that every SDK supports this instrumentation.

`grafana/sdk/mcp-sdk.json` visualizes the separate operation/error series.
Display names explain numeric RPC codes while retaining raw SDK metrics.

`otel/njs.yaml` extends the edge connector with outcome and bounded RPC-code
dimensions. Load it after edge.yaml. It keeps the same single HTTP request
counter; semantic outcomes come from NGINX's njs observer rather than SDK
execution spans. `grafana/njs/mcp-njs.json` adds edge outcome panels.

`otel/audit.yaml` tails structured NGINX audit files with a persistent
checkpoint and exports logs over OTLP to Loki. `loki/audit.yaml` provides
single-instance storage with only service name indexed. Event fields are
structured metadata, so request IDs remain searchable without creating
an indexed stream per request.

`grafana/audit/mcp-audit.json` shows readable event summaries and full JSON
with tool, decision, outcome and request-ID filters. It expects a Loki
datasource with UID `mcp-audit-loki`. See the
[searchable audit demo](../demo/searchable-audit/README.md).
