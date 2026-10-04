#!/bin/sh
# Antigravity PreToolUse guard. stdin carries the tool call, stdout carries the decision.
cat >/dev/null
printf '{"decision":"deny","reason":"BENCHMARK_NETWORK_POLICY_DENY: external retrieval and network-capable tools are disabled for this benchmark run."}\n'
