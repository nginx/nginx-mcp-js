// Copyright (C) Dmitry Volyntsev
// Copyright (c) F5, Inc.
//
// This source code is licensed under the Apache License, Version 2.0 license
// found in the LICENSE file in the root directory of this source tree.

package main

import (
	"bytes"
	"context"
	"crypto/rand"
	"encoding/json"
	"flag"
	"fmt"
	"hash/fnv"
	"io"
	"log"
	"math/big"
	"net/http"
	"sort"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"github.com/modelcontextprotocol/go-sdk/jsonrpc"
	"github.com/modelcontextprotocol/go-sdk/mcp"

	"mcp-demo/internal/tools"
)

const protocolVersion = "2026-07-28"

type clientProfile struct {
	name      string
	weight    int
	toolCount int
}

var clientProfiles = []clientProfile{
	{name: "client-red", weight: 1, toolCount: 4},
	{name: "client-green", weight: 2, toolCount: 6},
	{name: "client-blue", weight: 3, toolCount: 8},
	{name: "client-purple", weight: 1, toolCount: 8},
}

type config struct {
	url         string
	duration    time.Duration
	workers     int
	maxRequests int
	rps         int
	mix         scenarioMix
}

type scenarioMix struct {
	toolErrors    int
	rpcErrors     int
	headerErrors  int
	policyDenials int
	interim       int
}

func (mix scenarioMix) scenario(index int) string {
	// Spread each outcome across the cycle instead of generating error bursts.
	slot := (index % 100) * 37 % 100
	for _, item := range []struct {
		count int
		name  string
	}{
		{mix.toolErrors, "tool_error"},
		{mix.rpcErrors, "rpc_error"},
		{mix.headerErrors, "header_error"},
		{mix.policyDenials, "policy_denial"},
		{mix.interim, "input_required"},
	} {
		if slot < item.count {
			return item.name
		}
		slot -= item.count
	}
	return "success"
}

type stats struct {
	interim    atomic.Int64
	requests   atomic.Int64
	errors     atomic.Int64
	success    atomic.Int64
	bytesRx    atomic.Int64
	latencySum atomic.Int64
}

type toolDistribution struct {
	tools             []string
	cumulativeWeights []int
	totalWeight       int
}

type rpcRequest struct {
	JSONRPC string              `json:"jsonrpc"`
	ID      int64               `json:"id"`
	Method  string              `json:"method"`
	Params  *mcp.CallToolParams `json:"params"`
}

type rpcResponse struct {
	JSONRPC string          `json:"jsonrpc"`
	ID      json.RawMessage `json:"id"`
	Result  json.RawMessage `json:"result"`
	Error   *jsonrpc.Error  `json:"error"`
}

func main() {
	targetURL := flag.String(
		"url", "http://127.0.0.1:9000/mcp", "MCP endpoint URL")
	durationValue := flag.String("duration", "10s", "Benchmark duration")
	workers := flag.Int("workers", 10, "Number of concurrent workers")
	maxRequests := flag.Int(
		"max-requests", 0, "Maximum requests per worker (0 is unlimited)")
	rps := flag.Int("rps", 40, "Maximum aggregate requests per second")
	toolErrors := flag.Int("tool-error-percent", 10, "Tool error share")
	rpcErrors := flag.Int("rpc-error-percent", 5, "RPC error share")
	headerErrors := flag.Int("header-error-percent", 5, "Header mismatch share")
	policyDenials := flag.Int("policy-denial-percent", 5, "Edge denial share")
	interim := flag.Int("input-required-percent", 5, "Interim result share")
	flag.Parse()

	duration, err := time.ParseDuration(*durationValue)
	if err != nil {
		log.Fatalf("invalid duration: %v", err)
	}
	total := 0
	for _, percent := range []int{*toolErrors, *rpcErrors, *headerErrors,
		*policyDenials, *interim} {
		if percent < 0 || percent > 100 {
			log.Fatal("scenario percentages must be between 0 and 100")
		}
		total += percent
	}
	if total > 100 || *workers < 1 || *rps < 1 || duration <= 0 {
		log.Fatal("invalid mix, workers, request rate or duration")
	}

	cfg := &config{
		url:         *targetURL,
		duration:    duration,
		workers:     *workers,
		maxRequests: *maxRequests,
		rps:         *rps,
		mix: scenarioMix{*toolErrors, *rpcErrors, *headerErrors,
			*policyDenials, *interim},
	}

	log.Printf("starting MCP %s load generator", protocolVersion)
	log.Printf("target: %s", cfg.url)
	log.Printf("workers: %d", cfg.workers)
	log.Printf("mixed traffic: tool=%d%% RPC=%d%% HTTP400=%d%% "+
		"HTTP403=%d%% interim=%d%% success=%d%%, cap=%d rps",
		*toolErrors, *rpcErrors, *headerErrors, *policyDenials, *interim,
		100-total, *rps)

	toolNames := tools.Names()
	distributions := make(map[string]*toolDistribution)
	clientStats := make(map[string]*stats)
	for _, profile := range clientProfiles {
		clientStats[profile.name] = &stats{}
		count := min(profile.toolCount, len(toolNames))
		distributions[profile.name] = newToolDistribution(toolNames[:count])
	}

	var ctx context.Context
	var cancel context.CancelFunc
	if cfg.maxRequests > 0 {
		ctx, cancel = context.WithCancel(context.Background())
	} else {
		ctx, cancel = context.WithTimeout(
			context.Background(), cfg.duration)
	}
	defer cancel()

	start := time.Now()
	assignments := assignClients(cfg.workers)
	var wg sync.WaitGroup
	for _, profile := range assignments {
		wg.Add(1)
		go func() {
			defer wg.Done()
			runWorker(
				ctx,
				cfg,
				distributions[profile.name],
				clientStats[profile.name],
				profile,
			)
		}()
	}

	wg.Wait()
	cancel()
	printFinalStats(clientStats, time.Since(start))
}

func newToolDistribution(toolNames []string) *toolDistribution {
	distribution := &toolDistribution{
		tools:             make([]string, len(toolNames)),
		cumulativeWeights: make([]int, len(toolNames)),
	}

	for i, name := range toolNames {
		distribution.tools[i] = name
		distribution.totalWeight += deterministicWeight(name)
		distribution.cumulativeWeights[i] = distribution.totalWeight
	}
	return distribution
}

func deterministicWeight(value string) int {
	hash := fnv.New32a()
	_, _ = hash.Write([]byte(value))
	return int(hash.Sum32()%20) + 1
}

func (distribution *toolDistribution) selectTool() string {
	if distribution.totalWeight == 0 {
		return ""
	}

	value := randInt(distribution.totalWeight)
	index := sort.Search(
		len(distribution.cumulativeWeights),
		func(i int) bool {
			return distribution.cumulativeWeights[i] > value
		},
	)
	return distribution.tools[index]
}

func runWorker(
	ctx context.Context,
	cfg *config,
	distribution *toolDistribution,
	statistics *stats,
	profile clientProfile,
) {
	httpClient := &http.Client{Timeout: 30 * time.Second}
	ticker := time.NewTicker(time.Second * time.Duration(cfg.workers) /
		time.Duration(cfg.rps))
	defer ticker.Stop()
	var requestCount int
	var requestID int64

	for ctx.Err() == nil {
		if cfg.maxRequests > 0 && requestCount >= cfg.maxRequests {
			return
		}

		requestCount++
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
		}
		requestID++
		toolName := distribution.selectTool()
		scenario := cfg.mix.scenario(requestCount - 1)
		toolName = scenarioTool(toolName, scenario)
		started := time.Now()

		result, bytesRead, err := callTool(
			ctx,
			httpClient,
			cfg.url,
			profile.name,
			requestID,
			toolName,
			scenario,
		)

		statistics.requests.Add(1)
		statistics.bytesRx.Add(int64(bytesRead))
		statistics.latencySum.Add(time.Since(started).Microseconds())

		if err != nil || result.IsError {
			statistics.errors.Add(1)
			continue
		}

		if result.NeedsInput() {
			statistics.interim.Add(1)
			continue
		}

		statistics.success.Add(1)
	}
}

func scenarioTool(toolName, scenario string) string {
	switch scenario {
	case "tool_error":
		return "get_forecast"
	case "rpc_error":
		return "search_web"
	case "input_required":
		return "translate_text"
	default:
		return toolName
	}
}

func callTool(
	ctx context.Context,
	client *http.Client,
	url string,
	clientName string,
	requestID int64,
	toolName string,
	scenario string,
) (*mcp.CallToolResult, int, error) {
	arguments := randomArguments(toolName)
	arguments["simulate"] = scenario
	if scenario == "policy_denial" {
		toolName = "denied_demo_tool"
	}
	message := &rpcRequest{
		JSONRPC: "2.0",
		ID:      requestID,
		Method:  "tools/call",
		Params: &mcp.CallToolParams{
			Meta: mcp.Meta{
				mcp.MetaKeyProtocolVersion: protocolVersion,
				mcp.MetaKeyClientInfo: &mcp.Implementation{
					Name:    clientName,
					Version: "2.0",
				},
				mcp.MetaKeyClientCapabilities: map[string]any{},
			},
			Name:      toolName,
			Arguments: arguments,
		},
	}

	body, err := json.Marshal(message)
	if err != nil {
		return nil, 0, fmt.Errorf("marshal request: %w", err)
	}

	req, err := http.NewRequestWithContext(
		ctx, http.MethodPost, url, bytes.NewReader(body))
	if err != nil {
		return nil, 0, fmt.Errorf("create request: %w", err)
	}
	req.Header.Set("Accept", "application/json, text/event-stream")
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Mcp-Protocol-Version", protocolVersion)
	req.Header.Set("Mcp-Method", "tools/call")
	req.Header.Set("Mcp-Name", toolName)
	if scenario == "header_error" {
		req.Header.Set("Mcp-Name", "mismatching_demo_tool")
	}

	response, err := client.Do(req)
	if err != nil {
		return nil, 0, fmt.Errorf("send request: %w", err)
	}
	defer response.Body.Close()

	responseBody, err := io.ReadAll(io.LimitReader(response.Body, 1024*1024))
	if err != nil {
		return nil, 0, fmt.Errorf("read response: %w", err)
	}

	var envelope rpcResponse
	if err := json.Unmarshal(responseBody, &envelope); err != nil {
		return nil, len(responseBody), fmt.Errorf(
			"decode HTTP %d response: %w", response.StatusCode, err)
	}
	if envelope.Error != nil {
		return nil, len(responseBody), fmt.Errorf(
			"HTTP %d JSON-RPC %d: %s",
			response.StatusCode,
			envelope.Error.Code,
			envelope.Error.Message,
		)
	}
	if response.StatusCode != http.StatusOK {
		return nil, len(responseBody), fmt.Errorf(
			"unexpected HTTP status %d", response.StatusCode)
	}

	var result mcp.CallToolResult
	if err := json.Unmarshal(envelope.Result, &result); err != nil {
		return nil, len(responseBody), fmt.Errorf("decode result: %w", err)
	}
	return &result, len(responseBody), nil
}

func assignClients(workerCount int) []clientProfile {
	totalWeight := 0
	for _, profile := range clientProfiles {
		totalWeight += profile.weight
	}

	assignments := make([]clientProfile, workerCount)
	index := 0
	for _, profile := range clientProfiles {
		count := workerCount * profile.weight / totalWeight
		if count < 1 {
			count = 1
		}
		for i := 0; i < count && index < workerCount; i++ {
			assignments[index] = profile
			index++
		}
	}
	for index < workerCount {
		assignments[index] = clientProfiles[len(clientProfiles)-1]
		index++
	}
	return assignments
}

func randomArguments(toolName string) map[string]any {
	switch {
	case strings.Contains(toolName, "forecast"):
		return map[string]any{
			"latitude":  30.0 + randFloat()*20.0,
			"longitude": -120.0 + randFloat()*40.0,
		}
	case strings.Contains(toolName, "stock"):
		return map[string]any{"symbol": "MSFT"}
	case strings.Contains(toolName, "search"):
		return map[string]any{"query": "latest news"}
	default:
		return map[string]any{
			"arg1": randInt(100),
			"arg2": "test_value",
		}
	}
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

func randFloat() float64 {
	return float64(randInt(1000000)) / 1000000.0
}

func printFinalStats(clientStats map[string]*stats, duration time.Duration) {
	fmt.Println("=== Final Results ===")
	fmt.Printf("Duration: %v\n", duration)

	var totalRequests int64
	var totalSuccess int64
	var totalErrors int64
	var totalBytes int64

	for _, profile := range clientProfiles {
		statistics := clientStats[profile.name]
		requests := statistics.requests.Load()
		success := statistics.success.Load()
		errors := statistics.errors.Load()
		bytesRead := statistics.bytesRx.Load()
		latencySum := statistics.latencySum.Load()

		totalRequests += requests
		totalSuccess += success
		totalErrors += errors
		totalBytes += bytesRead

		averageLatency := 0.0
		if requests > 0 {
			averageLatency = float64(latencySum) / float64(requests) / 1000.0
		}

		fmt.Printf(
			"  [%s] Req: %d | OK: %d | Err: %d | Input: %d | Lat: %.2f ms\n",
			profile.name,
			requests,
			success,
			errors,
			statistics.interim.Load(),
			averageLatency,
		)
	}

	fmt.Printf("Total Requests: %d\n", totalRequests)
	fmt.Printf("Successful: %d\n", totalSuccess)
	fmt.Printf("Errors: %d\n", totalErrors)
	throughput := float64(totalRequests) / duration.Seconds()
	fmt.Printf("Throughput: %.2f Req/s\n", throughput)
	fmt.Printf("Total Data Received: %.2f MB\n", float64(totalBytes)/(1024*1024))
}
