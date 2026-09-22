#!/bin/bash
# Helper script to make MCP tool calls
# Usage: mcp_call.sh <port> <session_id> <tool_name> '<json_params>'

PORT=$1
MCP_SID=$2
TOOL=$3
PARAMS=$4

PAYLOAD=$(cat <<EOF
{"jsonrpc": "2.0", "method": "tools/call", "params": {"name": "$TOOL", "arguments": $PARAMS}, "id": 1}
EOF
)

curl -s -X POST http://127.0.0.1:$PORT/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "mcp-session-id: $MCP_SID" \
  -d "$PAYLOAD" 2>/dev/null
