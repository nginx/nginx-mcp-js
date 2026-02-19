# Copyright (C) Dmitry Volyntsev
# Copyright (C) F5, Inc.

FROM golang:1.24-alpine AS builder

RUN apk add --no-cache git

WORKDIR /build

COPY go.mod go.sum ./
COPY mcp_server.go mcp_client.go ./

RUN git clone --depth 1 \
    https://github.com/modelcontextprotocol/go-sdk.git \
    go-sdk/ \
 && go mod tidy

RUN CGO_ENABLED=0 go build -o mcp_server mcp_server.go \
 && CGO_ENABLED=0 go build -o mcp_client mcp_client.go


FROM alpine:latest

COPY --from=builder /build/mcp_server /mcp_server
COPY --from=builder /build/mcp_client /mcp_client

# No default ENTRYPOINT - let docker-compose specify the command
