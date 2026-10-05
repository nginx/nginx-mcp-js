// Copyright (C) Dmitry Volyntsev
// Copyright (c) F5, Inc.
//
// This source code is licensed under the Apache License, Version 2.0 license
// found in the LICENSE file in the root directory of this source tree.

package main

import (
	"context"
	"crypto/rand"
	"encoding/json"
	"flag"
	"fmt"
	"log"
	"math/big"
	"net/http"
	"strings"
	"time"

	"github.com/modelcontextprotocol/go-sdk/jsonrpc"
	"github.com/modelcontextprotocol/go-sdk/mcp"

	"mcp-demo/internal/tools"
)

var (
	allowSimulation = flag.Bool(
		"allow-simulation", false, "Enable deterministic demo outcomes")
	serverName = flag.String(
		"name", "mcp-server", "Server name reported in response metadata")
	backend = flag.String(
		"backend", "information", "Tool ownership group")
	port = flag.Int("port", 9001, "Server port")
	minLatency = flag.Duration(
		"min-latency", 5*time.Millisecond, "Minimum processing latency")
	maxLatency = flag.Duration(
		"max-latency", 50*time.Millisecond, "Maximum processing latency")
)

func main() {
	flag.Parse()

	toolNames := tools.NamesForBackend(*backend)
	if len(toolNames) == 0 {
		log.Fatalf("backend %q owns no tools", *backend)
	}

	server := mcp.NewServer(&mcp.Implementation{
		Name:    *serverName,
		Version: "2.0",
	}, nil)

	inputSchema := json.RawMessage(`{"type":"object"}`)
	for _, name := range toolNames {
		toolName := name
		server.AddTool(
			&mcp.Tool{
				Name:        toolName,
				Description: fmt.Sprintf("Demo tool: %s", toolName),
				InputSchema: inputSchema,
			},
			func(
				ctx context.Context,
				req *mcp.CallToolRequest,
			) (*mcp.CallToolResult, error) {
				var args map[string]any
				if *allowSimulation {
					if err := json.Unmarshal(req.Params.Arguments, &args); err != nil {
						return nil, &jsonrpc.Error{
							Code:    jsonrpc.CodeInvalidParams,
							Message: "invalid simulation arguments",
						}
					}
				}
				return handleToolCall(toolName, *serverName, args)
			},
		)
	}

	handler := mcp.NewStreamableHTTPHandler(
		func(r *http.Request) *mcp.Server {
			return server
		},
		&mcp.StreamableHTTPOptions{
			Stateless:                    true,
			JSONResponse:                 true,
			MaxRequestBodyBytes:          64 * 1024,
			PropagateRequestCancellation: true,
		},
	)

	addr := fmt.Sprintf(":%d", *port)
	log.Printf(
		"starting %s on %s, backend=%s, tools=%v",
		*serverName,
		addr,
		*backend,
		toolNames,
	)

	if err := http.ListenAndServe(addr, handler); err != nil {
		log.Fatalf("server failed: %v", err)
	}
}

func handleToolCall(
	toolName string,
	server string,
	args map[string]any,
) (*mcp.CallToolResult, error) {
	simulateLatency(toolName)

	switch args["simulate"] {
	case "rpc_error":
		return nil, &jsonrpc.Error{
			Code:    jsonrpc.CodeInternalError,
			Message: "internal error (simulated)",
		}
	case "tool_error":
		return &mcp.CallToolResult{
			Content: []mcp.Content{
				&mcp.TextContent{Text: "tool error (simulated)"},
			},
			IsError: true,
		}, nil
	case "input_required":
		return &mcp.CallToolResult{
			InputRequests: map[string]mcp.InputRequest{},
		}, nil
	case "large_response":
		return &mcp.CallToolResult{
			Content: []mcp.Content{
				&mcp.TextContent{Text: strings.Repeat("x", 70000)},
			},
		}, nil
	}
	text := fmt.Sprintf(
		`{"tool":%q,"server":%q,"status":"success",`+
			`"timestamp":%d}`,
		toolName,
		server,
		time.Now().Unix(),
	)

	return &mcp.CallToolResult{
		Content: []mcp.Content{
			&mcp.TextContent{Text: text},
		},
	}, nil
}

func simulateLatency(toolName string) {
	cap := *maxLatency
	switch toolName {
	case "query_db":
		cap *= 5
	case "resize_image":
		cap *= 3
	}

	rangeMilliseconds := int64(cap-*minLatency) / int64(time.Millisecond)
	if rangeMilliseconds <= 0 {
		time.Sleep(*minLatency)
		return
	}

	delta := time.Duration(randInt(int(rangeMilliseconds))) * time.Millisecond
	time.Sleep(*minLatency + delta)
}

func randInt(maximum int) int {
	if maximum <= 0 {
		return 0
	}
	n, err := rand.Int(rand.Reader, big.NewInt(int64(maximum)))
	if err != nil {
		panic(err)
	}
	return int(n.Int64())
}
