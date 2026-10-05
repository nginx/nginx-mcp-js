#!/usr/bin/env python3
# Copyright (C) Dmitry Volyntsev
# Copyright (C) F5, Inc.

import argparse
import json
import time
import urllib.error
import urllib.request
import urllib.parse

VERSION = "2026-07-28"
TOOLS = {
    "get_forecast": "information",
    "search_web": "information",
    "translate_text": "information",
    "resize_image": "operations",
    "send_email": "operations",
    "get_stock_price": "data",
    "calculate_sum": "data",
    "query_db": "data",
}


def message(tool="get_forecast", simulate="success"):
    return {
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {
            "name": tool, "arguments": {"simulate": simulate},
            "_meta": {
                "io.modelcontextprotocol/protocolVersion": VERSION,
                "io.modelcontextprotocol/clientCapabilities": {},
                "io.modelcontextprotocol/clientInfo": {
                    "name": "scenario-check", "version": "1.0",
                },
            },
        },
    }


def request(url, body, changes=None, method="POST"):
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": VERSION,
        "Mcp-Method": "tools/call", "Mcp-Name": "get_forecast",
    }
    for name, value in (changes or {}).items():
        if value is None:
            headers.pop(name, None)
        else:
            headers[name] = value
    data = json.dumps(body).encode() if isinstance(body, dict) else body
    req = urllib.request.Request(url, data=data, headers=headers,
                                 method=method)
    try:
        response = urllib.request.urlopen(req, timeout=10)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        raw = response.read()
        try:
            decoded = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            decoded = None
        return response.status, decoded, dict(response.headers), raw


def check(url, name, body, status, changes=None, method="POST", code=None):
    actual, result, headers, raw = request(url, body, changes, method)
    assert actual == status, (name, actual, status, raw)
    if code is not None:
        assert result["error"]["code"] == code, (name, result)
    if status in (400, 403, 404, 405, 415) or code is not None:
        assert headers.get("Content-Type", "").startswith(
            "application/json"), (name, headers)
        assert isinstance(result, dict) and "error" in result, (name, raw)
    print(f"PASS {name}: HTTP {actual}")
    return result, headers


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:9000/mcp")
    parser.add_argument("--prometheus")
    parser.add_argument("--sdk", action="store_true")
    parser.add_argument("--njs", action="store_true")
    parser.add_argument("--mixed", action="store_true")
    args = parser.parse_args()

    if args.mixed:
        assert args.prometheus, "--mixed requires --prometheus"
        queries = [
            'sum(rate(edge_calls_total{http_status_code="400"}[1m]))',
            'sum(rate(edge_calls_total{http_status_code="403"}[1m]))',
        ]
        if args.sdk:
            queries += [
                'sum(rate(mcp_exec_calls_total{error_type="tool_error"}[1m]))',
                'sum(rate(mcp_exec_calls_total{error_type="-32603"}[1m]))',
            ]
        for attempt in range(45):
            values = []
            for query in queries:
                url = args.prometheus.rstrip("/") + "/api/v1/query?" + (
                    urllib.parse.urlencode({"query": query}))
                with urllib.request.urlopen(url, timeout=5) as response:
                    values.append(json.load(response)["data"]["result"])
            if all(v and float(v[0]["value"][1]) > 0 for v in values):
                print("PASS background mixed traffic metrics")
                return
            time.sleep(2)
        raise AssertionError(("mixed traffic missing", values))

    for attempt in range(30):
        try:
            status, _, _, _ = request(args.url, message())
            if status == 200:
                break
        except (urllib.error.URLError, ConnectionError):
            pass
        time.sleep(1)
    else:
        raise AssertionError("MCP backends not ready after 30 seconds")

    for tool, backend in TOOLS.items():
        result, _ = check(args.url, tool, message(tool), 200,
                          {"Mcp-Name": tool})
        assert result["result"]["resultType"] == "complete", result
        assert not result["result"].get("isError"), result
        text = json.loads(result["result"]["content"][0]["text"])
        assert text["server"] == f"mcp-{backend}", text

    result, _ = check(args.url, "tool error", message(simulate="tool_error"),
                      200)
    assert result["result"]["isError"] is True, result
    check(args.url, "RPC error", message(simulate="rpc_error"), 200,
          code=-32603)
    result, _ = check(args.url, "interim result",
                      message(simulate="input_required"), 200)
    assert result["result"]["resultType"] == "input_required", result
    if args.njs:
        result, _ = check(args.url, "large response preserved",
                          message(simulate="large_response"), 200)
        assert len(result["result"]["content"][0]["text"]) == 70000
    check(args.url, "missing version", message(), 400,
          {"MCP-Protocol-Version": None}, code=-32020)
    check(args.url, "unsupported version", message(), 400,
          {"MCP-Protocol-Version": "2025-11-25"}, code=-32022)
    wrong = message()
    wrong["params"]["_meta"][
        "io.modelcontextprotocol/protocolVersion"] = "2025-11-25"
    check(args.url, "body version mismatch", wrong, 400, code=-32020)
    check(args.url, "missing method header", message(), 400,
          {"Mcp-Method": None}, code=-32020)
    check(args.url, "method header mismatch", message(), 400,
          {"Mcp-Method": "tools/list"}, code=-32020)
    check(args.url, "missing name header", message(), 400,
          {"Mcp-Name": None}, code=-32020)
    check(args.url, "name header mismatch", message(), 400,
          {"Mcp-Name": "query_db"}, code=-32020)
    for request_id in ("", "null", 0):
        with_id = message()
        with_id["id"] = request_id
        result, _ = check(args.url, f"request ID {request_id!r}", with_id, 200)
        assert result["id"] == request_id, result
    no_tool = message()
    del no_tool["params"]["name"]
    check(args.url, "missing tool", no_tool, 400, code=-32602)
    check(args.url, "edge tool policy", message("unknown"), 403,
          {"Mcp-Name": "unknown"})
    for method in ("server/discover", "tools/list"):
        other = message()
        other["method"] = method
        del other["params"]["name"]
        check(args.url, method, other, 404, {"Mcp-Method": method},
              code=-32601)
    for method in ("GET", "DELETE"):
        _, headers = check(args.url, method, None, 405, method=method)
        assert headers.get("Allow") == "POST", headers
    check(args.url, "unsupported media", message(), 415,
          {"Content-Type": "text/plain"})
    check(args.url, "malformed JSON", b"{", 400, code=-32600)
    escaped = json.dumps(message()).replace("get_forecast",
                                            "get_\\u0066orecast").encode()
    check(args.url, "escaped JSON name", escaped, 200)
    duplicate = json.dumps(message()).replace(
        '"name": "get_forecast"',
        '"name": "query_db", "name": "get_forecast"').encode()
    check(args.url, "duplicate key agrees with backend", duplicate, 200)
    check(args.url, "case-insensitive media type", message(), 200,
          {"Content-Type": "Application/JSON; charset=utf-8"})
    check(args.url, "encoded name rejected", message(), 400,
          {"Mcp-Name": "=?base64?Z2V0X2ZvcmVjYXN0?="}, code=-32020)
    large = message()
    large["params"]["arguments"]["padding"] = "x" * 63000
    check(args.url, "in-memory body boundary", large, 200)
    large["params"]["arguments"]["padding"] = "x" * 66000
    check(args.url, "body over limit", large, 413)

    if args.prometheus:
        query = "edge_calls_total"
        url = args.prometheus.rstrip("/") + "/api/v1/query?query=" + query
        for attempt in range(30):
            with urllib.request.urlopen(url, timeout=5) as response:
                metrics = json.load(response)["data"]["result"]
            codes = {item["metric"].get("http_status_code")
                     for item in metrics}
            if {"200", "400", "403", "404", "405", "415"} <= codes:
                print("PASS edge HTTP metrics")
                break
            time.sleep(2)
        else:
            raise AssertionError(("edge HTTP metrics missing", metrics))
        if args.njs:
            for attempt in range(30):
                with urllib.request.urlopen(url, timeout=5) as response:
                    metrics = json.load(response)["data"]["result"]
                outcomes = {item["metric"].get("mcp_outcome")
                            for item in metrics}
                if {"complete", "tool_error", "rpc_error",
                        "input_required", "unobserved"} <= outcomes:
                    print("PASS njs edge semantic metrics")
                    break
                time.sleep(2)
            else:
                raise AssertionError(("njs outcomes missing", metrics))
        if args.sdk:
            url = args.prometheus.rstrip("/") + (
                "/api/v1/query?query=mcp_exec_calls_total")
            for attempt in range(30):
                with urllib.request.urlopen(url, timeout=5) as response:
                    metrics = json.load(response)["data"]["result"]
                errors = {item["metric"].get("error_type")
                          for item in metrics}
                if {"tool_error", "-32603"} <= errors:
                    print("PASS SDK semantic metrics")
                    break
                time.sleep(2)
            else:
                raise AssertionError(("SDK metrics missing", metrics))


if __name__ == "__main__":
    main()
