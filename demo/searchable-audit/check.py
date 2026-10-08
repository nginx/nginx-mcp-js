#!/usr/bin/env python3
# Copyright (C) Dmitry Volyntsev
# Copyright (C) F5, Inc.

import argparse
import base64
import json
import pathlib
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

DEMO = pathlib.Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(DEMO / "shared" / "scenarios"))
from check import message, request


def get(url):
    auth = base64.b64encode(b"admin:admin").decode()
    req = urllib.request.Request(url, headers={
        "Authorization": "Basic " + auth})
    with urllib.request.urlopen(req, timeout=10) as response:
        return json.load(response)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:9000/mcp")
    parser.add_argument("--grafana", default="http://127.0.0.1:3000")
    args = parser.parse_args()
    grafana = args.grafana.rstrip("/")
    for attempt in range(60):
        try:
            if request(args.url, message())[0] == 200:
                get(grafana + "/api/health")
                break
        except (urllib.error.URLError, ConnectionError):
            pass
        time.sleep(1)
    else:
        raise AssertionError("MCP or Grafana not ready")

    start = int(time.time())
    cases = [
        ("Successful call", message(), {}, 200, "complete", ""),
        ("RPC error inside HTTP 200", message(simulate="rpc_error"), {},
         200, "rpc_error", ""),
        ("Header/body mismatch", message(), {"Mcp-Name": "search_web"},
         400, "unobserved", "tool_header_mismatch"),
    ]
    expected = {}
    for name, body, changes, status, outcome, reason in cases:
        actual, result, headers, raw = request(args.url, body, changes)
        assert actual == status, (name, actual, raw)
        if outcome == "rpc_error":
            assert result["error"]["code"] == -32603, result
        request_id = headers["X-Request-ID"]
        assert re.fullmatch(r"[0-9a-f]{32}", request_id)
        expected[request_id] = (name, status, outcome, reason)

    base = grafana + "/api/datasources/proxy/uid/mcp-audit-loki"

    def query(expression):
        params = urllib.parse.urlencode({
            "query": expression, "start": str(int(start * 1e9)),
            "end": str(time.time_ns()), "limit": 1000})
        return get(base + "/loki/api/v1/query_range?" + params)["data"][
            "result"]

    selector = '{service_name="nginx-mcp-edge"}'
    records = {}
    for attempt in range(60):
        try:
            for request_id in expected:
                streams = query(selector + f' | request_id="{request_id}"')
                values = [value for stream in streams
                          for value in stream["values"]]
                if values:
                    assert len(values) == 1, ("duplicate event", values)
                    records[request_id] = json.loads(values[0][1])
            if len(records) == len(expected):
                break
        except urllib.error.HTTPError as error:
            if error.code not in (502, 503):
                raise
        time.sleep(1)
    else:
        raise AssertionError(("audit ingestion incomplete", records))

    params = urllib.parse.urlencode({
        "match[]": selector, "start": str(int(start * 1e9)),
        "end": str(time.time_ns())})
    series = get(base + "/loki/api/v1/series?" + params)["data"]
    assert series, "no indexed audit streams"
    for labels in series:
        assert labels["service_name"] == "nginx-mcp-edge", labels
        assert set(labels) <= {"service_name", "__stream_shard__"}, labels

    dashboard = get(grafana + "/api/dashboards/uid/mcp-searchable-audit")[
        "dashboard"]
    local = json.loads((DEMO.parent / "observability" / "grafana" /
                        "audit" / "mcp-audit.json").read_text())
    assert dashboard["panels"] == local["panels"]
    for request_id, (name, status, outcome, reason) in expected.items():
        event = records[request_id]
        assert event["http"]["status"] == status, event
        assert event["mcp"]["outcome"] == outcome, event
        assert event["gateway"]["reason"] == reason, event
        assert event["upstream"]["attempted"] is (status == 200), event
        assert event["mcp"]["tool"] == "get_forecast", event
        if reason:
            assert event["mcp"]["header_tool"] == "search_web", event
        for panel in dashboard["panels"][1:]:
            expression = panel["targets"][0]["expr"]
            for variable, value in (
                    ("${request_id}", request_id),
                    ("${tool:regex}", "get_forecast"),
                    ("${decision:regex}", event["gateway"]["decision"]),
                    ("${outcome:regex}", outcome)):
                expression = expression.replace(variable, value)
            streams = query(expression)
            assert streams, (panel["title"], expression)
            if panel["id"] == 2:
                line = streams[0]["values"][0][1]
                assert f"HTTP {status}" in line and outcome in line, line
                assert request_id in line and (not reason or reason in line)
        link = grafana + "/d/mcp-searchable-audit?" + (
            urllib.parse.urlencode({"var-request_id": request_id}))
        print(f"\nPASS {name}: HTTP {status}, {outcome}")
        print(link)
    print("\nPASS Loki ingestion, request search and dashboard queries")


if __name__ == "__main__":
    main()
