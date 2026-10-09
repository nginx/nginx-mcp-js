# MCP OAuth resource protection with NGINX Plus

Protect an MCP endpoint using [MCP 2026-07-28 authorization][mcp].
Try allowed and denied tool calls from a web page or CLI, then see what
NGINX did in Grafana. Requires a [commercial subscription][subscription].

## NGINX

- Validate access tokens with [auth_jwt][jwt]: signature, expiry, issuer
  and audience. Fetch the identity provider's public keys with
  `auth_jwt_key_request`.
- Tell clients where to obtain authorization through resource metadata
  and a Bearer challenge. Missing or invalid tokens receive HTTP 401.
- Check tool permissions after authentication with
  [internal_redirect][redirect]. Insufficient scope receives HTTP 403.
- Replace caller identity headers with verified claims and remove the
  frontend Bearer token before forwarding to the MCP backend.
- Record the decision in audit logs and export traces with the optional
  [OpenTelemetry module][otel].

The key configuration looks like this:

```nginx
location = /mcp {
    auth_jwt "MCP";
    auth_jwt_key_request /_jwks;
    auth_jwt_require $mcp_token_profile;

    internal_redirect @mcp_authenticated;
}

location @mcp_authenticated {
    if ($mcp_scope_allowed = 0) {
        return 403;
    }

    proxy_set_header Authorization "";
    proxy_set_header X-User $jwt_claim_sub;
    proxy_pass http://information;
}
```

See [nginx.conf], [authorization.conf], [policy.mjs] and [audit.conf] for
the complete example, including MCP request checks and Bearer challenges.

## Demo environment

The Python application is the OAuth client. It discovers the identity
provider, opens browser login, obtains an access token using Authorization
Code + PKCE through [Authlib][authlib], and calls MCP through NGINX.
[Keycloak][keycloak] provides login, consent and tokens. The MCP backend
executes allowed tools and confirms the identity received from NGINX.

[Collector][collector], [Loki][loki], [Tempo][tempo] and [Grafana][grafana]
make the result visible: rejected requests stop at NGINX; accepted calls
continue into backend and tool spans. Each result links to its audit event
and trace. HTTP status and MCP outcome are shown separately.

NGINX runs locally using your binary and license. Everything else runs in
Docker. The page offers login, calls without authorization, insufficient
permissions, spoofed identity and invalid-token scenarios. Token fixtures
can run independently of browser login.

## Run

Requires Linux, Docker Compose and a recent licensed NGINX Plus or nginx-se
binary with HTTP SSL, JWT, internal redirect, JSON and njs/QuickJS support.
Install the matching [njs][njs-install] and [OTel][otel-install] modules or
build them for your binary.

From demo/:

```sh
export NGINX_BINARY=/absolute/path/to/nginx
export NGINX_LICENSE=/absolute/path/to/license.jwt
export NGINX_MODULES='load_module "/absolute/path/to/ngx_http_js_module.so";'
export NGINX_OTEL_MODULE=/absolute/path/to/ngx_otel_module.so

./oauth-resource-protection/run.sh up
```

With njs built into the binary, omit `NGINX_MODULES`. OTel is optional:
omit `NGINX_OTEL_MODULE` to run with audit logs only. Pass OTel through that
variable, rather than loading it again in `NGINX_MODULES`.

For source builds, enable `--with-http_ssl_module`,
`--with-http_auth_jwt_module`, `--with-http_json_module` and `--with-mgmt`.
Add njs using `--add-dynamic-module=/path/to/njs/nginx`, with the QuickJS
include/library paths, and run `make` and `make modules`. QuickJS must use
`-fPIC` when linked into a dynamic module. Follow the [OTel build guide][otel-build]
to build its module against the same NGINX build.

The runner checks the binary and modules before starting the environment
and reports missing capabilities. To check them separately:

```sh
./oauth-resource-protection/run.sh preflight
```

Open **https://localhost:4096** and choose **Log in and call a tool**.
Keycloak credentials: **alice / alice**. The demo uses a self-signed HTTPS
certificate. Your browser will show a certificate warning; proceed to open
the local demo.
Grafana is at **http://localhost:8001**, with credentials **admin / admin**.

Set `DEMO_PORT` and `GRAFANA_PORT` to change the ports. If accessing the demo
at another address, set `DEMO_PUBLIC_URL` to its HTTPS origin and
`GRAFANA_PUBLIC_URL` to the Grafana URL.

### CLI

```sh
./oauth-resource-protection/run.sh login
# Open the printed URL in your browser.
./oauth-resource-protection/run.sh scenario allowed-call
./oauth-resource-protection/run.sh scenario spoofed-identity
./oauth-resource-protection/run.sh check
```

**Clear application login** (`logout`) removes the application's tokens.
**Log out from IdP** (`idp-logout`) also ends Keycloak SSO; in CLI, open the
printed logout URL in your browser. Use IdP logout before clearing the
application login. Expired access tokens require a new login.

Stop the demo without re-exporting the binary or license:

```sh
./oauth-resource-protection/run.sh down
```

## Scope

This example protects direct calls to three known tools. It does not
aggregate catalogs or implement tenant isolation. The token profile is
configured for Keycloak; adapting another IdP requires matching its access
token format. Local test fixtures and the demo IdP are for illustration.

[policy.mjs]: policy.mjs
[nginx.conf]: nginx.conf
[authorization.conf]: authorization.conf
[audit.conf]: audit.conf
[mcp]: https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization
[jwt]: https://nginx.org/en/docs/http/ngx_http_auth_jwt_module.html
[redirect]: https://nginx.org/en/docs/http/ngx_http_internal_redirect_module.html
[otel]: https://nginx.org/en/docs/ngx_otel_module.html
[keycloak]: https://www.keycloak.org/securing-apps/oidc-layers
[authlib]: https://docs.authlib.org/en/latest/client/oauth2.html
[collector]: https://opentelemetry.io/docs/collector/
[loki]: https://grafana.com/docs/loki/latest/
[tempo]: https://grafana.com/docs/tempo/latest/
[grafana]: https://grafana.com/docs/grafana/latest/
[subscription]: https://www.f5.com/products/nginx
[njs-install]: https://docs.nginx.com/nginx/admin-guide/dynamic-modules/nginscript/
[otel-install]: https://docs.nginx.com/nginx/admin-guide/dynamic-modules/opentelemetry/
[otel-build]: https://github.com/nginxinc/nginx-otel#building
