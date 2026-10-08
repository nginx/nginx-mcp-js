#!/usr/bin/env python3
# Copyright (C) Dmitry Volyntsev
# Copyright (C) F5, Inc.

import argparse
import base64
import importlib.util
import json
import pathlib
import time
import urllib.error
import urllib.parse

DEMO = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "audit_check", DEMO / "searchable-audit" / "check.py")
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def attributes(values):
    return {item["key"]: next(iter(item["value"].values()))
            for item in values}


def span_id(value):
    return base64.b64decode(value).hex()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:9000/mcp")
    parser.add_argument("--grafana", default="http://127.0.0.1:3000")
    args = parser.parse_args()
    grafana = args.grafana.rstrip("/")
    records, expected = audit.main([
        "--url", args.url, "--grafana", grafana])
    base = grafana + "/api/datasources/proxy/uid/mcp-audit-tempo"

    for request_id, event in records.items():
        name, status, outcome, reason = expected[request_id]
        trace_id = event["trace_id"]
        trace = {}
        for attempt in range(60):
            try:
                trace = audit.get(base + "/api/traces/" + trace_id)
                spans = []
                for batch in trace.get("batches", []):
                    service = attributes(batch["resource"]["attributes"])[
                        "service.name"]
                    for scope in batch["scopeSpans"]:
                        for span in scope["spans"]:
                            spans.append((service, span))
                if len(spans) == (3 if status == 200 else 1):
                    break
            except urllib.error.HTTPError as error:
                if error.code not in (404, 502, 503):
                    raise
            time.sleep(1)
        else:
            raise AssertionError(("trace incomplete", name, trace))

        edge = [s for service, s in spans if service == "nginx-mcp-edge"]
        assert len(edge) == 1, spans
        edge = edge[0]
        assert span_id(edge["spanId"]) == event["span_id"], edge
        assert not edge.get("parentSpanId"), edge
        if status == 200:
            backend = [s for service, s in spans
                       if service == "mcp-information"]
            assert len(backend) == 2, spans
            http = next(s for s in backend if s["name"] == "MCP HTTP request")
            tool = next(s for s in backend
                        if s["name"] == "tools/call get_forecast")
            assert tool["parentSpanId"] == http["spanId"], spans
            assert http["parentSpanId"] == edge["spanId"], spans
            attr = attributes(tool["attributes"])
            assert attr["gen_ai.tool.name"] == "get_forecast", attr
            assert attr["mcp.outcome"] == outcome, attr
            assert int(tool["endTimeUnixNano"]) > int(
                tool["startTimeUnixNano"]), tool
            if outcome == "rpc_error":
                assert tool["status"]["code"] == "STATUS_CODE_ERROR", tool
                assert "simulated" in tool["status"]["message"], tool
                assert int(attr["mcp.rpc.code"]) == -32603, attr
        else:
            assert reason == "tool_header_mismatch", event
            assert len(spans) == 1, spans
        print(f"PASS {name}: " + " -> ".join(s["name"] for _, s in spans))

        query = '{service_name="nginx-mcp-edge"} | trace_id="' + trace_id + '"'
        params = urllib.parse.urlencode({
            "query": query, "start": str(int((time.time() - 120) * 1e9)),
            "end": str(time.time_ns())})
        result = audit.get(grafana +
            "/api/datasources/proxy/uid/mcp-audit-loki" +
            "/loki/api/v1/query_range?" + params)["data"]["result"]
        assert any(json.loads(value[1])["request_id"] == request_id
                   for stream in result for value in stream["values"])

    loki = audit.get(grafana + "/api/datasources/uid/mcp-audit-loki")
    tempo = audit.get(grafana + "/api/datasources/uid/mcp-audit-tempo")
    derived = loki["jsonData"]["derivedFields"][0]
    assert derived["datasourceUid"] == "mcp-audit-tempo", derived
    assert derived["matcherRegex"] == "trace_id", derived
    assert derived["matcherType"] == "label", derived
    reverse = tempo["jsonData"]["tracesToLogsV2"]
    assert reverse["datasourceUid"] == "mcp-audit-loki", reverse
    assert '${__trace.traceId}' in reverse["query"], reverse
    print("PASS span parentage, tool error and trace/log correlation")


if __name__ == "__main__":
    main()
