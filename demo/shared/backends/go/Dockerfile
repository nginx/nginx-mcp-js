# Copyright (C) Dmitry Volyntsev
# Copyright (C) F5, Inc.

ARG BUILDER_IMAGE=golang:1.25.9-alpine3.23@sha256:5caaf1cca9dc351e13deafbc3879fd4754801acba8653fa9540cea125d01a71f
FROM ${BUILDER_IMAGE} AS builder

RUN apk add --no-cache git

WORKDIR /build

COPY go.mod go.sum ./
RUN go mod download

COPY cmd/ cmd/
COPY internal/ internal/

RUN CGO_ENABLED=0 go build -o mcp_server ./cmd/server \
 && CGO_ENABLED=0 go build -o mcp_client ./cmd/client


FROM alpine:3.23.4@sha256:5b10f432ef3da1b8d4c7eb6c487f2f5a8f096bc91145e68878dd4a5019afde11

COPY --from=builder /build/mcp_server /mcp_server
COPY --from=builder /build/mcp_client /mcp_client
