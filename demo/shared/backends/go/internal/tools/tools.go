// Copyright (C) Dmitry Volyntsev
// Copyright (c) F5, Inc.
//
// This source code is licensed under the Apache License, Version 2.0 license
// found in the LICENSE file in the root directory of this source tree.

package tools

// Definition assigns a public tool name to its demo backend.
type Definition struct {
	Name    string
	Backend string
}

// Definitions is the static ownership registry used by the demo components.
var Definitions = []Definition{
	{Name: "get_forecast", Backend: "information"},
	{Name: "search_web", Backend: "information"},
	{Name: "translate_text", Backend: "information"},
	{Name: "resize_image", Backend: "operations"},
	{Name: "send_email", Backend: "operations"},
	{Name: "get_stock_price", Backend: "data"},
	{Name: "calculate_sum", Backend: "data"},
	{Name: "query_db", Backend: "data"},
}

// Names returns all public tool names in registry order.
func Names() []string {
	names := make([]string, 0, len(Definitions))
	for _, definition := range Definitions {
		names = append(names, definition.Name)
	}
	return names
}

// NamesForBackend returns the tools owned by backend.
func NamesForBackend(backend string) []string {
	var names []string
	for _, definition := range Definitions {
		if definition.Backend == backend {
			names = append(names, definition.Name)
		}
	}
	return names
}
