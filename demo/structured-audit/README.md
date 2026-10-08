# MCP structured gateway audit

Inspect individual [MCP] tool calls and gateway decisions as JSON events.

## NGINX

Extracts MCP metadata with [`json_set`][json-set] and writes request events
using [`log_format escape=json`][log-format] and [`access_log`][access-log].
Validation records rejection reasons; an [njs] response filter adds MCP
outcomes. Configure the format, filter and correlation IDs in the
[NGINX configuration](nginx.conf) and
[audit log destination](audit-logs.conf).

## Demo environment

Mock [Go SDK][go-sdk] backends return controlled results. The checker sends
calls and prints their JSON events from container logs, showing success, an RPC
error inside HTTP 200 and a request rejected before reaching upstream.

## Run and inspect

From demo/:

```sh
./run.sh structured-audit
./run.sh structured-audit stop mcp-client
python3 structured-audit/check.py
```

The checker prints the audit events for a successful call, an RPC error
inside HTTP 200, and a header/body mismatch rejected by NGINX. Compare
`http.status`, `mcp.outcome`, `gateway` and `upstream.attempted`: a selected
route does not mean the request reached the backend.

Watch the JSON event stream in another terminal:

```sh
./run.sh structured-audit logs --no-log-prefix -f nginx
```

Each response includes an NGINX-generated `X-Request-ID`. Copy an ID from
the checker output to find its event:

```sh
./run.sh structured-audit logs --no-log-prefix nginx | \
    grep '"request_id":"PASTE_REQUEST_ID_HERE"'
```

The checker also verifies rejection reasons, early body-size rejection,
JSON escaping and request-ID uniqueness. Stop with:

```sh
./run.sh structured-audit down
```

## Event scope

Header and body metadata are separate, so mismatches remain visible.
`gateway.reason` explains rejections; upstream fields describe connection
attempts, not proof of tool execution. The njs observer distinguishes MCP
errors in JSON responses. Unsupported or oversized responses remain
`unobserved`.

Client names are self-reported metadata, not authenticated identities.
Events exclude arguments, response bodies, credentials and query strings.
Trace IDs link events to spans when available; an early rejection may have
no span. This demo inspects logs in the terminal; searchable storage and
distributed trace inspection are separate follow-ups.

[MCP]: https://modelcontextprotocol.io/specification/2026-07-28
[json-set]: https://nginx.org/en/docs/http/ngx_http_json_module.html#json_set
[log-format]: https://nginx.org/en/docs/http/ngx_http_log_module.html#log_format
[access-log]: https://nginx.org/en/docs/http/ngx_http_log_module.html#access_log
[njs]: https://nginx.org/en/docs/njs/
[go-sdk]: https://pkg.go.dev/github.com/modelcontextprotocol/go-sdk@v1.7.0/mcp
