#!/usr/bin/env python3
# Copyright (C) Dmitry Volyntsev
# Copyright (C) F5, Inc.

import pathlib
import concurrent.futures
import json
import subprocess
import sys
import time
import urllib.parse
import urllib.request

sys.dont_write_bytecode = True
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]
                       / "shared/scenarios"))
from check import message, request


def call(tool="get_forecast", simulate="success"):
    return request("http://127.0.0.1:9000/mcp", message(tool, simulate),
                   {"Mcp-Name": tool})


def main():
    demo = pathlib.Path(__file__).resolve().parents[1]
    command = [str(demo / "run.sh"), "tool-circuit-breaking"]
    clients = ["mcp-client", "mcp-client-steady"]
    subprocess.run(command + ["stop"] + clients, check=True)
    try:
        time.sleep(11)
        for simulate in ("tool_error", "input_required"):
            for _ in range(4):
                assert call(simulate=simulate)[0] == 200
        assert call()[0] == 200
        print("PASS business errors and interim results do not open circuit")

        for _ in range(12):
            status, body, _, _ = call(simulate="rpc_error")
            if status == 503:
                break
            assert status == 200 and body["error"]["code"] == -32603
        else:
            raise AssertionError("circuit did not open")

        with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
            responses = list(pool.map(lambda _: call(), range(24)))
        workers = set()
        for status, body, headers, _ in responses:
            assert status == 503, status
            assert body == {"error": "Tool temporarily unavailable"}, body
            assert "X-MCP-Upstream-Status" not in headers, headers
            workers.add(headers["X-MCP-Worker"])
            assert call("search_web")[0] == 200
        assert len(workers) > 1, workers
        print("PASS shared circuit blocks tool across workers, not its neighbor")

        status, _, _, _ = request("http://127.0.0.1:9000/mcp", message(),
                                  {"Mcp-Name": "wrong"})
        assert status == 400
        print("PASS invalid metadata is rejected before circuit admission")

        time.sleep(11)
        status, _, headers, _ = call()
        assert status == 200 and headers["X-MCP-Upstream-Status"] == "200"
        print("PASS calls reach upstream after cooldown")
    finally:
        subprocess.run(command + ["start"] + clients, check=True)

    query = 'sum by (gen_ai_tool_name, mcp_breaker_admission, mcp_outcome) ' \
            '(edge_calls_total)'
    url = "http://127.0.0.1:9090/api/v1/query?" + urllib.parse.urlencode(
        {"query": query})
    for _ in range(30):
        with urllib.request.urlopen(url, timeout=5) as response:
            results = json.load(response)["data"]["result"]
        observed = {(item["metric"].get("gen_ai_tool_name"),
                     item["metric"].get("mcp_breaker_admission"),
                     item["metric"].get("mcp_outcome"))
                    for item in results if float(item["value"][1]) > 0}
        if {("get_forecast", "blocked", "unobserved"),
            ("get_forecast", "passed", "rpc_error"),
            ("search_web", "passed", "complete")} <= observed:
            assert not any(tool == "search_web" and state == "blocked"
                           for tool, state, _ in observed), observed
            print("PASS metrics distinguish failures and gateway blocks")
            break
        time.sleep(2)
    else:
        raise AssertionError(("breaker metrics missing", observed))


if __name__ == "__main__":
    main()
