#!/usr/bin/env python3
# Copyright (C) Dmitry Volyntsev
# Copyright (C) F5, Inc.

import concurrent.futures
import json
import pathlib
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.dont_write_bytecode = True
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]
                       / "shared/scenarios"))
from check import message, request


def call(tool):
    return request("http://127.0.0.1:9000/mcp", message(tool),
                   {"Mcp-Name": tool})


def main():
    demo = pathlib.Path(__file__).resolve().parents[1]
    clients = ["mcp-client", "mcp-client-steady"]
    command = [str(demo / "run.sh"), "tool-rate-limiting"]
    subprocess.run(command + ["stop"] + clients, check=True)
    try:
        time.sleep(1)
        for _ in range(30):
            try:
                if call("search_web")[0] == 200:
                    break
            except (urllib.error.URLError, ConnectionError):
                pass
            time.sleep(1)
        else:
            raise AssertionError("MCP backend not ready")
        time.sleep(1)
        with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
            responses = list(pool.map(lambda _: call("get_forecast"),
                                      range(12)))
        assert {r[0] for r in responses} == {200, 429}, responses
        for status, body, headers, raw in responses:
            if status == 429:
                assert headers["Content-Type"].startswith("application/json")
                assert body == {"error": "Tool rate limit exceeded"}, raw
                assert "X-MCP-Upstream-Status" not in headers, headers
            else:
                assert headers["X-MCP-Upstream-Status"] == "200", headers
        print("PASS NGINX rejects excess calls without an upstream response")
        assert call("search_web")[0] == 200
        print("PASS another tool on the same backend remains available")
        status, _, _, _ = request("http://127.0.0.1:9000/mcp", message(),
                                  {"Mcp-Name": "wrong"})
        assert status == 400, status
        print("PASS invalid metadata is rejected before rate limiting")
        time.sleep(1)
        assert call("get_forecast")[0] == 200
        print("PASS calls recover after excess traffic stops")
    finally:
        subprocess.run(command + ["start"] + clients, check=True)

    query = 'sum by (gen_ai_tool_name, http_status_code) (' \
            'rate(edge_calls_total{mcp_rate_limit_status!=""}[1m]))'
    url = "http://127.0.0.1:9090/api/v1/query?" + urllib.parse.urlencode(
        {"query": query})
    for _ in range(30):
        with urllib.request.urlopen(url, timeout=5) as response:
            results = json.load(response)["data"]["result"]
        rates = {(item["metric"]["gen_ai_tool_name"],
                  item["metric"]["http_status_code"]):
                 float(item["value"][1]) for item in results}
        if (rates.get(("get_forecast", "200"), 0) > 0
            and rates.get(("get_forecast", "429"), 0) > 0
            and rates.get(("search_web", "200"), 0) > 0):
            assert rates.get(("search_web", "429"), 0) == 0, rates
            print("PASS metrics show forwarded calls and isolated rejections")
            break
        time.sleep(2)
    else:
        raise AssertionError(("rate-limit metrics missing", rates))


if __name__ == "__main__":
    main()
