#!/usr/bin/env python3
# Copyright (C) Dmitry Volyntsev
# Copyright (C) F5, Inc.

import argparse
import datetime
import json
import pathlib
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse

DEMO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DEMO / "shared" / "scenarios"))
from check import VERSION, message, request


def events(since):
    result = subprocess.run(
        [str(DEMO / "run.sh"), "structured-audit", "logs",
         "--no-log-prefix", "--since", since, "nginx"],
        check=True, capture_output=True, text=True)
    records = []
    for line in result.stdout.splitlines():
        if line.startswith('{"schema":"nginx.mcp.audit.v1"'):
            records.append(json.loads(line))
    return records


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:9000/mcp")
    args = parser.parse_args()

    for attempt in range(30):
        try:
            if request(args.url, message())[0] == 200:
                break
        except (urllib.error.URLError, ConnectionError):
            pass
        time.sleep(1)
    else:
        raise AssertionError("MCP backends not ready")

    since = datetime.datetime.now(datetime.timezone.utc).isoformat()
    cases = []
    secret = "audit-body-must-not-appear"
    client = 'audit "client"\\name\nnext-line'

    def call(name, body, status, reason="", outcome="unobserved",
             changes=None, method="POST"):
        headers = {"Authorization": "Bearer audit-token-must-not-appear",
                   "X-Request-ID": "caller-supplied-id"}
        headers.update(changes or {})
        url = args.url + ("&" if "?" in args.url else "?") + (
            urllib.parse.urlencode({"private": secret}))
        actual, result, response_headers, raw = request(
            url, body, headers, method)
        assert actual == status, (name, actual, raw)
        request_id = response_headers.get("X-Request-ID", "")
        assert re.fullmatch(r"[0-9a-f]{32}", request_id), response_headers
        if outcome == "complete":
            assert not result["result"].get("isError"), result
        if outcome == "rpc_error":
            assert result["error"]["code"] == -32603, result
        cases.append((name, request_id, status, reason, outcome))

    success = message()
    success["params"]["arguments"]["private"] = secret
    success["params"]["_meta"][
        "io.modelcontextprotocol/clientInfo"]["name"] = client
    call("successful tool call", success, 200, outcome="complete")
    call("RPC error inside HTTP 200", message(simulate="rpc_error"), 200,
         outcome="rpc_error")
    call("header/body mismatch", message(), 400, "tool_header_mismatch",
         changes={"Mcp-Name": "search_web"})
    call("unknown tool", message("unknown"), 403, "tool_denied",
         changes={"Mcp-Name": "unknown"})
    call("tool error", message(simulate="tool_error"), 200,
         outcome="tool_error")
    call("interim result", message(simulate="input_required"), 200,
         outcome="input_required")
    call("oversized response", message(simulate="large_response"), 200)
    call("missing protocol version", message(), 400,
         "missing_protocol_version",
         changes={"MCP-Protocol-Version": None})
    call("unsupported version", message(), 400,
         "unsupported_protocol_version",
         changes={"MCP-Protocol-Version": "2025-11-25"})
    wrong = message()
    wrong["params"]["_meta"][
        "io.modelcontextprotocol/protocolVersion"] = "2025-11-25"
    call("body version mismatch", wrong, 400, "protocol_version_mismatch")
    call("method header mismatch", message(), 400,
         "method_header_mismatch", changes={"Mcp-Method": "tools/list"})
    other = message()
    other["method"] = "tools/list"
    call("unsupported RPC method", other, 404, "unsupported_rpc_method",
         changes={"Mcp-Method": "tools/list"})
    missing = message()
    del missing["params"]["name"]
    call("missing tool", missing, 400, "missing_tool")
    call("malformed JSON", b"{", 400, "invalid_request")
    call("HTTP method", None, 405, "http_method_not_allowed", method="GET")
    call("media type", message(), 415, "unsupported_media_type",
         changes={"Content-Type": "text/plain"})
    large = message()
    large["params"]["arguments"]["padding"] = "x" * 66000
    call("early body rejection", large, 413, "body_too_large")
    call("validation priority", message(), 415, "unsupported_media_type",
         changes={"Content-Type": "text/plain",
                  "MCP-Protocol-Version": None, "Mcp-Name": "unknown"})

    ids = {case[1] for case in cases}
    assert len(ids) == len(cases)
    for attempt in range(30):
        records = events(since)
        matching = [r for r in records if r["request_id"] in ids]
        if len(matching) == len(cases):
            break
        time.sleep(0.2)
    else:
        raise AssertionError(("missing audit events", matching, cases))
    indexed = {r["request_id"]: r for r in matching}
    assert len(indexed) == len(cases), "duplicate audit events"

    for number, (name, request_id, status, reason, outcome) in enumerate(cases):
        event = indexed[request_id]
        assert event["http"]["status"] == status, event
        assert event["gateway"]["reason"] == reason, event
        attempted = status == 200
        assert event["upstream"]["attempted"] is attempted, event
        assert event["gateway"]["decision"] == (
            "forwarded" if attempted else "rejected"), event
        assert event["mcp"]["outcome"] == outcome, event
        if attempted:
            assert event["upstream"]["status"] == "200", event
            assert re.fullmatch(r"[0-9a-f]{32}", event["trace_id"]), event
            assert re.fullmatch(r"[0-9a-f]{16}", event["span_id"]), event
        else:
            assert event["upstream"]["address"] in ("", "-"), event
        if number < 3:
            print(f"\n{name}: X-Request-ID={request_id}")
            print(json.dumps(event, indent=2, ensure_ascii=False))
        else:
            print(f"PASS {name}")

    first = indexed[cases[0][1]]
    assert first["mcp"]["client"] == client, first
    assert first["mcp"]["protocol_version"] == VERSION, first
    mismatch = indexed[cases[2][1]]
    assert mismatch["mcp"]["tool"] == "get_forecast", mismatch
    assert mismatch["mcp"]["header_tool"] == "search_web", mismatch
    assert mismatch["gateway"]["route"] == "mcp-information", mismatch
    assert indexed[cases[1][1]]["mcp"]["rpc_code"] == "-32603"
    serialized = json.dumps(matching)
    for excluded in (secret, "audit-token-must-not-appear",
                     "caller-supplied-id"):
        assert excluded not in serialized, excluded
    print("\nPASS audit correlation, escaping and excluded payloads")


if __name__ == "__main__":
    main()
