# Copyright (C) Dmitry Volyntsev
# Copyright (C) F5, Inc.

# Stage 1: Build Go MCP client and server
FROM golang:1.24-alpine AS mcp-builder

RUN apk add --no-cache git

WORKDIR /build

COPY demo/mcp/ .

RUN git clone --depth 1 \
    https://github.com/modelcontextprotocol/go-sdk.git \
    go-sdk/ \
 && go mod tidy

RUN CGO_ENABLED=0 go build -o mcp_server mcp_server.go \
 && CGO_ENABLED=0 go build -o mcp_client mcp_client.go


# Stage 2: Runtime image (nginx + njs + otel modules pre-installed)
FROM nginx:alpine-otel

ARG TARGETARCH

ARG OTELCOL_VERSION=0.146.1
ARG PROMETHEUS_VERSION=3.9.1
ARG GRAFANA_VERSION=12.3.3

RUN apk add --no-cache curl

# otelcol-contrib
RUN curl -fsSL \
    "https://github.com/open-telemetry/opentelemetry-collector-releases/releases/download/v${OTELCOL_VERSION}/otelcol-contrib_${OTELCOL_VERSION}_linux_${TARGETARCH}.tar.gz" \
    | tar xz -C /usr/local/bin otelcol-contrib

# prometheus
RUN curl -fsSL \
    "https://github.com/prometheus/prometheus/releases/download/v${PROMETHEUS_VERSION}/prometheus-${PROMETHEUS_VERSION}.linux-${TARGETARCH}.tar.gz" \
    | tar xz --strip-components=1 -C /usr/local/bin \
        "prometheus-${PROMETHEUS_VERSION}.linux-${TARGETARCH}/prometheus"

# grafana
RUN curl -fsSL \
    "https://dl.grafana.com/oss/release/grafana-${GRAFANA_VERSION}.linux-${TARGETARCH}.tar.gz" \
    | tar xz -C /opt \
 && mv /opt/grafana-${GRAFANA_VERSION} /opt/grafana

# MCP binaries
COPY --from=mcp-builder /build/mcp_server \
    /build/mcp_client /usr/local/bin/

# nginx config
COPY demo/nginx/mcp.conf /etc/nginx/nginx.conf
COPY mcp.js /etc/nginx/mcp.js

# otel config
COPY demo/otel/config.yaml /etc/otel/config.yaml

# prometheus config
COPY demo/prometheus/prometheus.yaml \
    /etc/prometheus/prometheus.yaml

# grafana provisioning
COPY demo/grafana/provisioning/ \
    /etc/grafana/provisioning/

COPY demo/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8001

ENTRYPOINT ["/entrypoint.sh"]
