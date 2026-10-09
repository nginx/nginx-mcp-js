FROM nginx:1.31.6-alpine-otel@sha256:f237a3efb7233a400a89c2bbb16c68dc4036de731c143a2a87160b3c9238f0b3

RUN apk add --no-cache perl perl-test-harness

ENV TEST_NGINX_BINARY=/usr/sbin/nginx
WORKDIR /workspace
ENTRYPOINT ["perl", "-MApp::Prove", "-e", "my $p = App::Prove->new; $p->process_args(@ARGV); exit(!$p->run)", "--", "-I", "/nginx-tests/lib"]
CMD ["t/mcp_routing.t"]
