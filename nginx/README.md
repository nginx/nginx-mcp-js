# MCP NGINX configuration snippets

Use these snippets with NGINX 1.31.5+ built with `--with-http_json_module`.
The examples use 1.31.6 and load `ngx_otel_module.so` for tracing.

| Snippet | Context | Contract |
| --- | --- | --- |
| mcp-metadata.conf | http | Extracts method, tool, version and client; requires a deployment map defining $mcp_upstream |
| mcp-body.conf | server | Early read for JSON; keeps bodies within the 64 KiB memory buffer |
| mcp-errors.conf | location | Defines fixed JSON-RPC rejection strings with id:null |
| mcp-validation.conf | location | Uses metadata/error variables and $mcp_upstream; rejects invalid or denied direct calls |
| mcp-otel.conf | server/location | Exports known tool/backend, protocol and upstream attributes; requires OTel module |
| mcp-njs.conf | http | Declares observer import and request state; requires njs/mcp-observer.mjs and JS module |

Load metadata at http scope and supply an allowlist map from
`$mcp_body_tool` to `$mcp_upstream` (empty means denied). Metadata maps
unknown names to an empty `$mcp_observed_tool` for bounded metric labels.
Then include body handling at server scope, and errors before validation
inside the /mcp location. Set proxy_pass and proxy buffering in the
deployment configuration. Validation uses `@mcp_method_not_allowed`;
define that named location to return 405 with `Allow: POST`.

The snippets target direct MCP 2026-07-28 tools/call. Adapt supported
versions, body limits and policy to your deployment. If you raise the body
limit, raise the in-memory buffer too. Early reading uses server settings
before location selection; location-level limits do not configure it.
JSON extraction does not retain value types or distinguish an absent ID
from an empty string ID. ID and full envelope validation belong to the
backend. An unreadable method receives Invalid request, not Parse error:
extraction cannot distinguish malformed JSON from a missing method.
These are composable recipes, not
a complete JSON-RPC validator or a federated MCP implementation.

See [the native nginx.conf](../demo/native-routing/nginx.conf) for assembly and
[the root README](../README.md) for the key settings.
