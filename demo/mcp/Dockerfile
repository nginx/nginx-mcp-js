# Copyright (C) Dmitry Volyntsev
# Copyright (C) F5, Inc.

FROM golang:1.25.9-alpine3.23@sha256:5caaf1cca9dc351e13deafbc3879fd4754801acba8653fa9540cea125d01a71f AS builder

RUN apk add --no-cache git

WORKDIR /build

COPY go.mod go.sum ./
COPY mcp_server.go mcp_client.go ./

RUN git clone --depth 1 --branch v1.6.0 \
    https://github.com/modelcontextprotocol/go-sdk.git \
    go-sdk/ \
 && go mod tidy

RUN CGO_ENABLED=0 go build -o mcp_server mcp_server.go \
 && CGO_ENABLED=0 go build -o mcp_client mcp_client.go


FROM alpine:3.23.4@sha256:5b10f432ef3da1b8d4c7eb6c487f2f5a8f096bc91145e68878dd4a5019afde11

COPY --from=builder /build/mcp_server /mcp_server
COPY --from=builder /build/mcp_client /mcp_client

# No default ENTRYPOINT - let docker-compose specify the command
