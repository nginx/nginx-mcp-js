# MCP JSON response observer

[mcp-observer.mjs](mcp-observer.mjs) is a reusable njs response filter.
It observes JSON-RPC tool responses while forwarding the original buffers.

Load ngx_http_js_module, set `js_engine qjs` at http scope (recommended),
and include nginx/snippets/mcp-njs.conf there.
Set `js_body_filter observer.observe buffer_type=buffer` in the
proxy location. Export `$mcp_outcome` and `$mcp_rpc_code` as OTel attributes.
The module stores Buffer chunks in its own property on the request object
and requires the standard `$upstream_status` variable. It uses no global
accumulator or NGINX variable for intermediate response data.

| Outcome | Meaning |
| --- | --- |
| complete | Complete result with content and no tool error |
| tool_error | Complete result with isError:true |
| rpc_error | JSON-RPC error; bounded code in $mcp_rpc_code |
| input_required | Interim result, not a completed tool success/failure |
| invalid_response | Invalid JSON or response envelope |
| unobserved | Non-upstream response, unsupported encoding/media type or byte cap |

Observation is capped at 64 KiB. Chunks are joined once at the end before
UTF-8 decoding, preserving characters split across buffers. Larger
responses are still forwarded in full. SSE and compressed responses are
unobserved; this is a JSON-only observer,
not a general MCP/SSE parser or full schema validator.

Known RPC codes remain numeric; other codes become `other` for bounded
metric dimensions. Tool errors do not imply unhealthy infrastructure.
Run `node t/mcp_observer.mjs` from the root for classifier/filter tests.
See [the complete example](../demo/njs-response-observability/README.md).
