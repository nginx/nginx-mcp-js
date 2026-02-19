// Copyright (c) F5, Inc.
//
// This source code is licensed under the Apache License, Version 2.0 license found in the
// LICENSE file in the root directory of this source tree.

package main

import (
	"context"
	"crypto/rand"
	"flag"
	"fmt"
	"hash/fnv"
	"log"
	"math/big"
	"net/http"
	"sort"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"github.com/modelcontextprotocol/go-sdk/mcp"
)

// Client identity with traffic weight and target endpoint
type ClientProfile struct {
	Name            string
	Weight          int
	Endpoint        string
	ToolCount       int
	ToolsPerSession int
}

var clientProfiles = []ClientProfile{
	{"client-red", 1, "/mcp-stable", 4, 3},
	{"client-green", 2, "/mcp-flaky", 6, 7},
	{"client-blue", 3, "/mcp-sluggish", 8, 21},
	{"client-purple", 1, "/mcp-stable", 8, 1000},
}

// Configuration
type Config struct {
	URL         string
	Duration    time.Duration
	Workers     int
	MaxRequests int
	ToolCount   int
}

// Statistics
type Stats struct {
	Requests   atomic.Int64
	Errors     atomic.Int64
	Success    atomic.Int64
	BytesRx    atomic.Int64
	LatencySum atomic.Int64 // Microseconds
}

// ToolDistribution handles weighted random selection of tools
type ToolDistribution struct {
	Tools             []string
	CumulativeWeights []int
	TotalWeight       int
}

func NewToolDistribution(toolNames []string) *ToolDistribution {
	td := &ToolDistribution{
		Tools:             make([]string, len(toolNames)),
		CumulativeWeights: make([]int, len(toolNames)),
	}

	currentTotal := 0
	fmt.Println("--- Tool Frequency Distribution (Deterministic) ---")
	for i, name := range toolNames {
		td.Tools[i] = name
		weight := getDeterministicWeight(name)
		currentTotal += weight
		td.CumulativeWeights[i] = currentTotal
		fmt.Printf("[%s] Weight: %d (%.1f%%)\n", name, weight,
			float64(weight)/float64(currentTotal)*100)
	}
	td.TotalWeight = currentTotal
	fmt.Println("---------------------------------------------------")
	return td
}

func getDeterministicWeight(s string) int {
	h := fnv.New32a()
	h.Write([]byte(s))
	return int(h.Sum32()%20) + 1
}

func (td *ToolDistribution) Select() string {
	if td.TotalWeight == 0 {
		return ""
	}
	r := randInt(td.TotalWeight)
	idx := sort.Search(len(td.CumulativeWeights), func(i int) bool {
		return td.CumulativeWeights[i] > r
	})
	if idx < len(td.Tools) {
		return td.Tools[idx]
	}
	return td.Tools[len(td.Tools)-1]
}

// Tool definitions for variety
var baseToolNames = []string{
	"get_forecast", "get_stock_price", "search_web", "translate_text",
	"calculate_sum", "resize_image", "send_email", "query_db",
}

func main() {
	targetURL := flag.String("url", "http://127.0.0.1:9000", "Base URL (endpoint path appended per client)")
	durationStr := flag.String("duration", "10s", "Benchmark duration (e.g., 10s, 1m)")
	workers := flag.Int("workers", 10, "Number of concurrent workers")
	maxRequests := flag.Int("max-requests", 0, "Max number of requests per worker (0 = unlimited)")
	toolCount := flag.Int("tools", len(baseToolNames), "Number of distinct tool names to generate")
	flag.Parse()

	duration, err := time.ParseDuration(*durationStr)
	if err != nil {
		log.Fatalf("Invalid duration: %v", err)
	}

	config := &Config{
		URL:         *targetURL,
		Duration:    duration,
		Workers:     *workers,
		MaxRequests: *maxRequests,
		ToolCount:   *toolCount,
	}

	fmt.Printf("Starting MCP Mock Client\n")
	fmt.Printf("Target: %s\n", config.URL)
	if config.MaxRequests > 0 {
		fmt.Printf("Duration: Unlimited (capped by %d requests/worker)\n",
			config.MaxRequests)
	} else {
		fmt.Printf("Duration: %s\n", config.Duration)
	}
	fmt.Printf("Workers: %d\n", config.Workers)
	fmt.Printf("Tools Variety: %d\n", config.ToolCount)

	toolNames := generateTools(config.ToolCount)

	clientToolDists := make(map[string]*ToolDistribution)
	clientStats := make(map[string]*Stats)
	for _, p := range clientProfiles {
		clientStats[p.Name] = &Stats{}
		count := p.ToolCount
		if count > len(toolNames) {
			count = len(toolNames)
		}
		fmt.Printf("--- %s tools (%d/%d) ---\n",
			p.Name, count, len(toolNames))
		clientToolDists[p.Name] = NewToolDistribution(
			toolNames[:count])
	}

	var ctx context.Context
	var cancel context.CancelFunc

	if config.MaxRequests > 0 {
		ctx, cancel = context.WithCancel(context.Background())
	} else {
		ctx, cancel = context.WithTimeout(context.Background(), config.Duration)
	}
	defer cancel()

	var wg sync.WaitGroup

	startTime := time.Now()

	assignments := assignClients(config.Workers)
	for i := 0; i < config.Workers; i++ {
		wg.Add(1)
		go func(workerID int, profile ClientProfile) {
			defer wg.Done()
			runWorker(ctx, config,
				clientToolDists[profile.Name],
				clientStats[profile.Name],
				workerID, profile)
		}(i, assignments[i])
	}

	// Status Printer
	go func() {
		ticker := time.NewTicker(1 * time.Second)
		defer ticker.Stop()
		for {
			select {
			case <-ctx.Done():
				return
			case <-ticker.C:
				elapsed := time.Since(startTime).Seconds()
				var reqs, errs, rpss []string
				for _, p := range clientProfiles {
					s := clientStats[p.Name]
					r := s.Requests.Load()
					reqs = append(reqs, fmt.Sprintf("%d", r))
					errs = append(errs,
						fmt.Sprintf("%d", s.Errors.Load()))
					rpss = append(rpss,
						fmt.Sprintf("%.0f", float64(r)/elapsed))
				}
				fmt.Printf("Requests: (%s) | Errors: (%s) | RPS: (%s)\n",
					strings.Join(reqs, "/"),
					strings.Join(errs, "/"),
					strings.Join(rpss, "/"))
			}
		}
	}()

	wg.Wait()
	cancel()
	printFinalStats(clientStats, time.Since(startTime))
}

func runWorker(ctx context.Context, cfg *Config, tools *ToolDistribution, stats *Stats, workerID int, profile ClientProfile) {
	var reqCount int

	for {
		if ctx.Err() != nil {
			return
		}

		if cfg.MaxRequests > 0 && reqCount >= cfg.MaxRequests {
			return
		}

		client := mcp.NewClient(&mcp.Implementation{
			Name:    profile.Name,
			Version: "1.0",
		}, nil)

		transport := &mcp.StreamableClientTransport{
			Endpoint: cfg.URL + profile.Endpoint,
			HTTPClient: &http.Client{
				Timeout: 30 * time.Second,
			},
			DisableStandaloneSSE: true,
		}

		session, err := client.Connect(ctx, transport, nil)
		if err != nil {
			log.Printf("Worker %d [%s]: connect: %v, retrying in 2s",
				workerID, profile.Name, err)
			select {
			case <-ctx.Done():
				return
			case <-time.After(2 * time.Second):
			}
			continue
		}

		for i := 0; i < profile.ToolsPerSession; i++ {
			if ctx.Err() != nil {
				session.Close()
				return
			}

			if cfg.MaxRequests > 0 && reqCount >= cfg.MaxRequests {
				session.Close()
				return
			}

			reqCount++
			tool := tools.Select()
			start := time.Now()

			result, err := session.CallTool(ctx,
				&mcp.CallToolParams{
					Name:      tool,
					Arguments: generateRandomArgs(tool),
				})

			duration := time.Since(start).Microseconds()

			stats.Requests.Add(1)
			stats.LatencySum.Add(duration)

			if err != nil {
				stats.Errors.Add(1)
				continue
			}

			if result.IsError {
				stats.Errors.Add(1)
				continue
			}

			for _, c := range result.Content {
				if tc, ok := c.(*mcp.TextContent); ok {
					stats.BytesRx.Add(int64(len(tc.Text)))
				}
			}

			stats.Success.Add(1)
		}

		session.Close()
	}
}

func assignClients(numWorkers int) []ClientProfile {
	totalWeight := 0
	for _, p := range clientProfiles {
		totalWeight += p.Weight
	}

	assignments := make([]ClientProfile, numWorkers)

	idx := 0
	for _, p := range clientProfiles {
		count := numWorkers * p.Weight / totalWeight
		if count < 1 {
			count = 1
		}

		for j := 0; j < count && idx < numWorkers; j++ {
			assignments[idx] = p
			idx++
		}
	}

	for idx < numWorkers {
		assignments[idx] = clientProfiles[len(clientProfiles)-1]
		idx++
	}

	fmt.Println("--- Client Distribution ---")
	counts := make(map[string]int)
	for _, a := range assignments {
		counts[a.Name]++
	}
	for _, p := range clientProfiles {
		fmt.Printf("[%s -> %s] Workers: %d\n",
			p.Name, p.Endpoint, counts[p.Name])
	}
	fmt.Println("---------------------------")

	return assignments
}

func generateTools(count int) []string {
	tools := make([]string, count)
	for i := 0; i < count; i++ {
		if i < len(baseToolNames) {
			tools[i] = baseToolNames[i]
		} else {
			tools[i] = fmt.Sprintf("tool_%d", i)
		}
	}
	return tools
}

func generateRandomArgs(toolName string) map[string]interface{} {
	args := make(map[string]interface{})

	if strings.Contains(toolName, "forecast") {
		args["latitude"] = 30.0 + (randFloat() * 20.0)
		args["longitude"] = -120.0 + (randFloat() * 40.0)
	} else if strings.Contains(toolName, "stock") {
		args["symbol"] = "MSFT"
	} else if strings.Contains(toolName, "search") {
		args["query"] = "latest news"
	} else {
		args["arg1"] = randInt(100)
		args["arg2"] = "test_value"
	}
	return args
}

func randInt(max int) int {
	n, _ := rand.Int(rand.Reader, big.NewInt(int64(max)))
	return int(n.Int64())
}

func randFloat() float64 {
	n, _ := rand.Int(rand.Reader, big.NewInt(1000000))
	return float64(n.Int64()) / 1000000.0
}

func printFinalStats(clientStats map[string]*Stats, duration time.Duration) {
	fmt.Println("=== Final Results ===")
	fmt.Printf("Duration: %v\n", duration)

	var totalReq, totalOk, totalErr, totalBytes int64

	for _, p := range clientProfiles {
		s := clientStats[p.Name]
		req := s.Requests.Load()
		ok := s.Success.Load()
		errs := s.Errors.Load()
		bytes := s.BytesRx.Load()
		latSum := s.LatencySum.Load()

		totalReq += req
		totalOk += ok
		totalErr += errs
		totalBytes += bytes

		avgLat := 0.0
		if req > 0 {
			avgLat = float64(latSum) / float64(req) / 1000.0
		}

		fmt.Printf("  [%s] Req: %d | OK: %d | Err: %d | RPS: %.2f | Lat: %.2f ms\n",
			p.Name, req, ok, errs,
			float64(req)/duration.Seconds(), avgLat)
	}

	fmt.Printf("Total Requests: %d\n", totalReq)
	fmt.Printf("Successful: %d\n", totalOk)
	fmt.Printf("Errors: %d\n", totalErr)
	fmt.Printf("Throughput: %.2f Req/s\n",
		float64(totalReq)/duration.Seconds())
	fmt.Printf("Total Data Received: %.2f MB\n",
		float64(totalBytes)/1024/1024)
}
