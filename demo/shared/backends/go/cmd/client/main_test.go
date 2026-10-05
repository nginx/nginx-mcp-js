// Copyright (C) Dmitry Volyntsev
// Copyright (C) F5, Inc.

package main

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestMixedRequests(t *testing.T) {
	counts := map[string]int{}
	server := httptest.NewServer(http.HandlerFunc(func(
		w http.ResponseWriter, r *http.Request,
	) {
		var body rpcRequest
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			t.Error(err)
			return
		}
		arguments := body.Params.Arguments.(map[string]any)
		scenario := arguments["simulate"].(string)
		counts[scenario]++
		switch scenario {
		case "header_error":
			if body.Params.Name != "calculate_sum" ||
				r.Header.Get("Mcp-Name") == body.Params.Name {
				t.Error("header failure must keep original body tool")
			}
		case "policy_denial":
			if body.Params.Name != "denied_demo_tool" ||
				r.Header.Get("Mcp-Name") != body.Params.Name {
				t.Error("policy denial must have consistent routing metadata")
			}
		default:
			want := "calculate_sum"
			switch scenario {
			case "tool_error":
				want = "get_forecast"
			case "rpc_error":
				want = "search_web"
			case "input_required":
				want = "translate_text"
			}
			if body.Params.Name != want ||
				r.Header.Get("Mcp-Name") != body.Params.Name {
				t.Error("semantic scenario must retain valid tool routing")
			}
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"jsonrpc":"2.0","id":1,"result":` +
			`{"resultType":"complete","content":[]}}`))
	}))
	defer server.Close()

	mix := scenarioMix{10, 5, 5, 5, 5}
	for i := 0; i < 100; i++ {
		scenario := mix.scenario(i)
		tool := scenarioTool("calculate_sum", scenario)
		_, _, err := callTool(context.Background(), server.Client(),
			server.URL, "test", int64(i), tool, scenario)
		if err != nil {
			t.Fatal(err)
		}
	}
	for name, want := range map[string]int{
		"tool_error": 10, "rpc_error": 5, "header_error": 5,
		"policy_denial": 5, "input_required": 5, "success": 70,
	} {
		if counts[name] != want {
			t.Errorf("%s: got %d, want %d", name, counts[name], want)
		}
	}
}
