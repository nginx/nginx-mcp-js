#!/usr/bin/perl

use warnings;
use strict;

use JSON::PP;
use Test::More;

BEGIN { use FindBin; chdir($FindBin::Bin); }

use Test::Nginx;

select STDERR; $| = 1;
select STDOUT; $| = 1;

my $t = Test::Nginx->new()->has(qw/http proxy rewrite/)->plan(14);

for my $name (qw/mcp-metadata mcp-body mcp-validation mcp-errors/) {
    open my $file, '<', "../nginx/snippets/$name.conf" or die $!;
    local $/;
    $t->write_file("$name.conf", <$file>);
}

$t->write_file_expand('nginx.conf', <<'EOF');
%%TEST_GLOBALS%%
daemon off;
events {
}
http {
    %%TEST_GLOBALS_HTTP%%
    include %%TESTDIR%%/mcp-metadata.conf;
    map $mcp_body_tool $mcp_upstream {
        default "";
        get_forecast mcp-information;
    }

    upstream mcp-information {
        server 127.0.0.1:8081;
    }

    server {
        listen 127.0.0.1:8080;
        include %%TESTDIR%%/mcp-body.conf;

        location = /mcp {
            include %%TESTDIR%%/mcp-errors.conf;
            include %%TESTDIR%%/mcp-validation.conf;
            proxy_pass http://$mcp_upstream/mcp;
        }

        location @mcp_method_not_allowed {
            default_type application/json;
            add_header Allow POST always;
            return 405 '{"error":"HTTP method must be POST"}';
        }
    }

    server {
        listen 127.0.0.1:8081;
        location / {
            return 200 'proxied';
        }
    }
}
EOF

$t->try_run('no JSON module or early body read support');

like(mcp_request('tools/call', 'get_forecast'), qr/^HTTP\/1.. 200 /m,
    'matching metadata is proxied');
like(mcp_request('tools/call', 'other'), qr/^HTTP\/1.. 400 /m,
    'mismatching name rejected');
like(mcp_request('other', 'get_forecast'), qr/^HTTP\/1.. 400 /m,
    'mismatching method rejected');
like(mcp_request('tools/call', undef), qr/^HTTP\/1.. 400 /m,
    'missing name header rejected');
my $missing = mcp_request('tools/call', 'get_forecast', undef);
like($missing, qr/^HTTP\/1.. 400 /m, 'missing version rejected');
like($missing, qr/"code":-32020/, 'missing version is header mismatch');
my $unsupported = mcp_request('tools/call', 'get_forecast', '2025-11-25');
like($unsupported, qr/^HTTP\/1.. 400 /m, 'unsupported version rejected');
like($unsupported, qr/"code":-32022/, 'unsupported version code');
my $denied = mcp_request('tools/call', 'unknown', '2026-07-28', 'unknown');
like($denied, qr/^HTTP\/1.. 403 /m, 'unknown tool is edge policy denial');
like($denied, qr/Content-Type: application\/json.*"error":/s,
    'policy denial has JSON body');
my $malformed = mcp_request('tools/call', 'get_forecast', '2026-07-28',
    'get_forecast', '{');
like($malformed, qr/^HTTP\/1.. 400 /m, 'malformed body rejected');
like($malformed, qr/"code":-32600/, 'unreadable method is invalid request');
like(mcp_request('tools/call', 'get_forecast', '2026-07-28',
    'get_forecast', undef, '2025-11-25'), qr/^HTTP\/1.. 400 /m,
    'body version mismatch rejected');
like(mcp_request('tools/list', 'get_forecast', '2026-07-28',
    'get_forecast', undef, '2026-07-28', 'tools/list'),
    qr/^HTTP\/1.. 404 /m, 'unsupported method rejected');

sub mcp_request {
    my ($method, $tool, $version, $body_tool, $raw, $body_version,
        $body_method) = @_;
    $version = '2026-07-28' if @_ < 3;
    $body_tool //= 'get_forecast';
    $body_version //= '2026-07-28';
    $body_method //= 'tools/call';
    my $body = $raw // encode_json({
        jsonrpc => '2.0', id => 1, method => $body_method,
        params => { name => $body_tool, arguments => {}, _meta => {
            'io.modelcontextprotocol/protocolVersion' => $body_version,
        } },
    });
    my $headers = '';
    $headers .= "Mcp-Method: $method\r\n" if defined $method;
    $headers .= "Mcp-Name: $tool\r\n" if defined $tool;
    $headers .= "MCP-Protocol-Version: $version\r\n" if defined $version;

    return http("POST /mcp HTTP/1.1\r\nHost: localhost\r\n"
        . "Content-Type: application/json\r\n" . $headers
        . "Content-Length: " . length($body)
        . "\r\nConnection: close\r\n\r\n" . $body);
}
