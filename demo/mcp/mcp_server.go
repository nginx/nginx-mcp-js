package main

import (
	"context"
	"crypto/rand"
	"encoding/base64"
	"encoding/json"
	"flag"
	"fmt"
	"log"
	"math/big"
	"net/http"
	"time"

	"github.com/modelcontextprotocol/go-sdk/jsonrpc"
	"github.com/modelcontextprotocol/go-sdk/mcp"
)

var (
	serverName    = flag.String("name", "mcp-mock-server", "Server name reported in initialize")
	port          = flag.Int("port", 9001, "Server port")
	errorRate     = flag.Float64("error-rate", 0.05, "Probability of returning a protocol error (0.0-1.0)")
	toolErrorRate = flag.Float64("tool-error-rate", 0.05, "Probability of returning a tool error (0.0-1.0)")
	longRespRate  = flag.Float64("long-rate", 0.10, "Probability of returning a large response (0.0-1.0)")
	minLatency    = flag.Duration("min-latency", 5*time.Millisecond, "Minimum processing latency")
	maxLatency    = flag.Duration("max-latency", 50*time.Millisecond, "Maximum processing latency (for normal requests)")
)

var toolNames = []string{
	"get_forecast", "get_stock_price", "search_web", "translate_text",
	"calculate_sum", "resize_image", "send_email", "query_db",
}

func main() {
	flag.Parse()

	server := mcp.NewServer(&mcp.Implementation{
		Name:    *serverName,
		Version: "1.0",
	}, nil)

	inputSchema := json.RawMessage(`{"type":"object"}`)

	for _, name := range toolNames {
		toolName := name
		server.AddTool(
			&mcp.Tool{
				Name:        toolName,
				Description: fmt.Sprintf("Mock tool: %s", toolName),
				InputSchema: inputSchema,
			},
			func(ctx context.Context, req *mcp.CallToolRequest) (*mcp.CallToolResult, error) {
				return handleToolCall(toolName)
			},
		)
	}

	handler := mcp.NewStreamableHTTPHandler(
		func(r *http.Request) *mcp.Server {
			return server
		},
		nil,
	)

	addr := fmt.Sprintf(":%d", *port)
	fmt.Printf("Starting MCP Mock Server '%s' on %s\n", *serverName, addr)
	fmt.Printf("  Protocol Error Rate: %.2f\n", *errorRate)
	fmt.Printf("  Tool Error Rate: %.2f\n", *toolErrorRate)
	fmt.Printf("  Long Response Rate: %.2f\n", *longRespRate)

	if err := http.ListenAndServe(addr, handler); err != nil {
		log.Fatalf("Server failed: %v", err)
	}
}

func handleToolCall(toolName string) (*mcp.CallToolResult, error) {
	simulateLatency(toolName)

	roll := randFloat()

	// Protocol error
	if roll < *errorRate {
		return nil, &jsonrpc.Error{
			Code:    jsonrpc.CodeInternalError,
			Message: "Internal error (simulated)",
		}
	}

	// Tool error
	if roll < *errorRate+*toolErrorRate {
		result := &mcp.CallToolResult{
			Content: []mcp.Content{
				&mcp.TextContent{
					Text: fmt.Sprintf("Error executing tool %s: unable to fetch data.", toolName),
				},
			},
			IsError: true,
		}
		return result, nil
	}

	// Success
	var text string
	if randFloat() < *longRespRate {
		size := 5000 + randInt(10000)
		text = generateLargeResponse(toolName, size)
	} else {
		text = fmt.Sprintf(`{"tool":"%s","status":"success","message":"Operation completed successfully","timestamp":%d}`,
			toolName, time.Now().Unix())
	}

	return &mcp.CallToolResult{
		Content: []mcp.Content{
			&mcp.TextContent{Text: text},
		},
	}, nil
}

func simulateLatency(toolName string) {
	var duration time.Duration

	var cap time.Duration

	switch toolName {
	case "query_db":
		cap = *maxLatency * 5
	case "resize_image":
		cap = *maxLatency * 3
	default:
		cap = *maxLatency
	}

	rangeMs := int64(cap-*minLatency) / 1e6
	if rangeMs <= 0 {
		duration = *minLatency
	} else {
		duration = *minLatency + time.Duration(randInt(int(rangeMs)))*time.Millisecond
	}

	time.Sleep(duration)
}

func generateLargeResponse(toolName string, size int) string {
	blob := generateRandomString(size)
	return fmt.Sprintf(`{"tool":"%s","status":"success","type":"large_blob","data":"%s"}`,
		toolName, blob)
}

func randInt(max int) int {
	n, _ := rand.Int(rand.Reader, big.NewInt(int64(max)))
	return int(n.Int64())
}

func randFloat() float64 {
	n, _ := rand.Int(rand.Reader, big.NewInt(1000000))
	return float64(n.Int64()) / 1000000.0
}

func generateRandomString(n int) string {
	b := make([]byte, n)
	rand.Read(b)
	return base64.StdEncoding.EncodeToString(b)
}
