#!/usr/bin/env bash
set -uo pipefail

CFG="${CLAUDE_SETTINGS_FILE:-${HOME}/.claude/settings.json}"
TIMEOUT_SECONDS="${TIMEOUT_SECONDS:-90}"
CONCURRENCY="${CONCURRENCY:-4}"
FULL_1M="${FULL_1M:-0}"
PASS=0
FAIL=0
WARN=0

need() {
  command -v "$1" >/dev/null 2>&1 || {
    printf '[FATAL] Missing command: %s\n' "$1"
    exit 1
  }
}

pass() {
  PASS=$((PASS + 1))
  printf '[PASS] %s\n' "$1"
}

fail() {
  FAIL=$((FAIL + 1))
  printf '[FAIL] %s\n' "$1"
}

warn() {
  WARN=$((WARN + 1))
  printf '[WARN] %s\n' "$1"
}

need jq
need curl
need grep
need python3
need claude
need timeout

if ! [[ "$TIMEOUT_SECONDS" =~ ^[1-9][0-9]*$ ]]; then
  printf '[FATAL] TIMEOUT_SECONDS must be a positive integer\n'
  exit 1
fi
if ! [[ "$CONCURRENCY" =~ ^[1-9][0-9]*$ ]]; then
  printf '[FATAL] CONCURRENCY must be a positive integer\n'
  exit 1
fi
if [[ ! -f "$CFG" ]]; then
  printf '[FATAL] Settings file not found: %s\n' "$CFG"
  exit 1
fi
if ! jq -e . "$CFG" >/dev/null 2>&1; then
  printf '[FATAL] Invalid JSON: %s\n' "$CFG"
  exit 1
fi

BASE="$(jq -r '.env.ANTHROPIC_BASE_URL // empty' "$CFG")"
TOKEN="$(jq -r '.env.ANTHROPIC_AUTH_TOKEN // empty' "$CFG")"
MODEL="$(jq -r '.env.ANTHROPIC_MODEL // .env.CLAUDE_CODE_SUBAGENT_MODEL // empty' "$CFG")"

if [[ -z "$BASE" || -z "$TOKEN" || -z "$MODEL" ]]; then
  printf '[FATAL] Missing ANTHROPIC_BASE_URL, ANTHROPIC_AUTH_TOKEN, or ANTHROPIC_MODEL\n'
  exit 1
fi

BASE="${BASE%/}"
WORK="$(mktemp -d /tmp/claude-endpoint-compat.XXXXXX)"
AUTH_FILE="${WORK}/auth.headers"
REPORT="${WORK}/summary.txt"

chmod 700 "$WORK"
umask 077
printf 'Authorization: Bearer %s\n' "$TOKEN" >"$AUTH_FILE"

cleanup() {
  rm -f "$AUTH_FILE"
  unset TOKEN
}
trap cleanup EXIT INT TERM

normalize_json_response() {
  local output="$1"

  [[ -s "$output" ]] || return 0
  python3 - "$output" <<'PY'
import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
raw = path.read_text(encoding="utf-8")
text = raw.lstrip()
try:
    value, end = json.JSONDecoder().raw_decode(text)
except json.JSONDecodeError:
    raise SystemExit(0)

trailer = text[end:].strip()
if trailer:
    path.with_suffix(path.suffix + ".raw").write_text(raw, encoding="utf-8")
    path.with_suffix(path.suffix + ".trailer").write_text(trailer + "\n", encoding="utf-8")
path.write_text(json.dumps(value, ensure_ascii=False) + "\n", encoding="utf-8")
PY
}

request() {
  local method="$1"
  local url="$2"
  local body="$3"
  local output="$4"
  local headers="$5"
  local code

  if [[ -n "$body" ]]; then
    code="$(
      curl -sS \
        --max-time "$TIMEOUT_SECONDS" \
        -X "$method" \
        -D "$headers" \
        -o "$output" \
        -w '%{http_code}' \
        -H "@$AUTH_FILE" \
        -H 'anthropic-version: 2023-06-01' \
        -H 'content-type: application/json' \
        --data-binary "@$body" \
        "$url"
    )"
  else
    code="$(
      curl -sS \
        --max-time "$TIMEOUT_SECONDS" \
        -X "$method" \
        -D "$headers" \
        -o "$output" \
        -w '%{http_code}' \
        -H "@$AUTH_FILE" \
        -H 'anthropic-version: 2023-06-01' \
        "$url"
    )"
  fi

  normalize_json_response "$output"
  printf '%s' "${code:-000}"
}

printf '%s\n' 'Claude endpoint compatibility probe'
printf 'Endpoint: %s\n' "$BASE"
printf 'Configured API model: %s\n' "$MODEL"
printf 'Claude Code version: %s\n' "$(claude --version 2>&1 | tr '\n' ' ')"
printf 'Artifacts: %s\n\n' "$WORK"

MODELS_CODE="$(
  request GET \
    "${BASE}/models" \
    '' \
    "${WORK}/models.json" \
    "${WORK}/models.headers"
)"

if [[ "$MODELS_CODE" == "200" ]] && jq -e . "${WORK}/models.json" >/dev/null 2>&1; then
  pass 'GET /models returns valid JSON'
else
  warn "GET /models unavailable or non-standard (HTTP ${MODELS_CODE}); Claude Code may still work"
fi

jq -n --arg model "$MODEL" '{
  model: $model,
  max_tokens: 64,
  messages: [{role: "user", content: "Reply with exactly ENDPOINT_OK"}]
}' >"${WORK}/basic.request.json"

BASIC_CODE="$(
  request POST \
    "${BASE}/messages" \
    "${WORK}/basic.request.json" \
    "${WORK}/basic.response.json" \
    "${WORK}/basic.headers"
)"

if [[ "$BASIC_CODE" == "200" ]] &&
   jq -e '
     .type == "message" and
     .role == "assistant" and
     (.content | type == "array") and
     (.content | any(.type == "text")) and
     (.stop_reason | type == "string") and
     (.usage.input_tokens | type == "number") and
     (.usage.output_tokens | type == "number")
   ' "${WORK}/basic.response.json" >/dev/null 2>&1; then
  pass 'Messages API basic schema'
  printf '       Response model: %s\n' "$(jq -r '.model // "(missing)"' "${WORK}/basic.response.json")"
else
  fail "Messages API basic schema (HTTP ${BASIC_CODE})"
fi

jq -n --arg model "$MODEL" '{
  model: $model,
  max_tokens: 128,
  messages: [{
    role: "user",
    content: "Call compat_probe with value 42. Do not answer in text."
  }],
  tools: [{
    name: "compat_probe",
    description: "Required endpoint compatibility probe.",
    input_schema: {
      type: "object",
      properties: {value: {type: "integer", description: "Probe value"}},
      required: ["value"],
      additionalProperties: false
    }
  }],
  tool_choice: {type: "tool", name: "compat_probe"}
}' >"${WORK}/tool.request.json"

TOOL_CODE="$(
  request POST \
    "${BASE}/messages" \
    "${WORK}/tool.request.json" \
    "${WORK}/tool.response.json" \
    "${WORK}/tool.headers"
)"

if [[ "$TOOL_CODE" == "200" ]] &&
   jq -e '
     .stop_reason == "tool_use" and
     (.content | any(
       .type == "tool_use" and
       .name == "compat_probe" and
       (.id | type == "string") and
       (.input | type == "object") and
       .input.value == 42
     ))
   ' "${WORK}/tool.response.json" >/dev/null 2>&1; then
  pass 'Anthropic tool_use schema'
else
  fail "Anthropic tool_use schema (HTTP ${TOOL_CODE})"
fi

TOOL_ID="$(
  jq -r '.content[]? | select(.type == "tool_use") | .id' \
    "${WORK}/tool.response.json" 2>/dev/null |
    python3 -c 'import sys; print(sys.stdin.readline().strip())'
)"

if [[ -n "$TOOL_ID" ]]; then
  jq -n \
    --arg model "$MODEL" \
    --arg tool_id "$TOOL_ID" \
    --slurpfile first "${WORK}/tool.response.json" \
    '{
      model: $model,
      max_tokens: 128,
      tools: [{
        name: "compat_probe",
        description: "Required endpoint compatibility probe.",
        input_schema: {
          type: "object",
          properties: {value: {type: "integer"}},
          required: ["value"],
          additionalProperties: false
        }
      }],
      messages: [
        {
          role: "user",
          content: "Call compat_probe with value 42. Do not answer in text."
        },
        {role: "assistant", content: $first[0].content},
        {
          role: "user",
          content: [{
            type: "tool_result",
            tool_use_id: $tool_id,
            content: "Probe succeeded"
          }]
        }
      ]
    }' >"${WORK}/tool-result.request.json"

  TOOL_RESULT_CODE="$(
    request POST \
      "${BASE}/messages" \
      "${WORK}/tool-result.request.json" \
      "${WORK}/tool-result.response.json" \
      "${WORK}/tool-result.headers"
  )"

  if [[ "$TOOL_RESULT_CODE" == "200" ]] &&
     jq -e '
       .stop_reason == "end_turn" and
       (.content | any(.type == "text"))
     ' "${WORK}/tool-result.response.json" >/dev/null 2>&1; then
    pass 'tool_use -> tool_result -> final response'
  else
    fail "tool_result round trip (HTTP ${TOOL_RESULT_CODE})"
  fi
else
  fail 'tool_result round trip skipped because tool_use ID is missing'
fi

jq '. + {stream: true}' "${WORK}/basic.request.json" >"${WORK}/stream.request.json"

curl -sS -N \
  --max-time "$TIMEOUT_SECONDS" \
  -H "@$AUTH_FILE" \
  -H 'anthropic-version: 2023-06-01' \
  -H 'content-type: application/json' \
  --data-binary "@${WORK}/stream.request.json" \
  "${BASE}/messages" \
  >"${WORK}/stream.response.sse"

STREAM_OK=1
for event in \
  message_start \
  content_block_start \
  content_block_delta \
  content_block_stop \
  message_delta \
  message_stop
do
  if ! grep -q "^event: ${event}" "${WORK}/stream.response.sse"; then
    STREAM_OK=0
    printf '       Missing SSE event: %s\n' "$event"
  fi
done

if [[ "$STREAM_OK" == "1" ]]; then
  pass 'Streaming SSE event sequence'
else
  fail 'Streaming SSE event sequence'
fi

jq '. + {stream: true}' "${WORK}/tool.request.json" >"${WORK}/tool-stream.request.json"

curl -sS -N \
  --max-time "$TIMEOUT_SECONDS" \
  -H "@$AUTH_FILE" \
  -H 'anthropic-version: 2023-06-01' \
  -H 'content-type: application/json' \
  --data-binary "@${WORK}/tool-stream.request.json" \
  "${BASE}/messages" \
  >"${WORK}/tool-stream.response.sse"

if grep -Eq '"type"[[:space:]]*:[[:space:]]*"input_json_delta"' "${WORK}/tool-stream.response.sse" &&
   grep -Eq '"stop_reason"[[:space:]]*:[[:space:]]*"tool_use"' "${WORK}/tool-stream.response.sse"; then
  pass 'Streaming tool input_json_delta'
else
  fail 'Streaming tool input_json_delta'
fi

jq -n --arg model "$MODEL" '{
  model: $model,
  max_tokens: 256,
  thinking: {type: "adaptive"},
  output_config: {effort: "low"},
  messages: [{role: "user", content: "Reply with exactly THINKING_API_OK"}]
}' >"${WORK}/thinking.request.json"

THINKING_CODE="$(
  request POST \
    "${BASE}/messages" \
    "${WORK}/thinking.request.json" \
    "${WORK}/thinking.response.json" \
    "${WORK}/thinking.headers"
)"

if [[ "$THINKING_CODE" == "200" ]] &&
   jq -e '
     .type == "message" and
     (.content | type == "array") and
     (.stop_reason | type == "string")
   ' "${WORK}/thinking.response.json" >/dev/null 2>&1; then
  pass 'Adaptive thinking and effort request accepted'
else
  fail "Adaptive thinking and effort request rejected (HTTP ${THINKING_CODE})"
fi

python3 - <<'PY' >"${WORK}/cache-prefix.txt"
print("Stable endpoint compatibility context. " * 1200)
PY

jq -n \
  --arg model "$MODEL" \
  --rawfile prefix "${WORK}/cache-prefix.txt" \
  '{
    model: $model,
    max_tokens: 32,
    system: [{
      type: "text",
      text: $prefix,
      cache_control: {type: "ephemeral"}
    }],
    messages: [{role: "user", content: "Reply with exactly CACHE_OK"}]
  }' >"${WORK}/cache.request.json"

CACHE1_CODE="$(
  request POST \
    "${BASE}/messages" \
    "${WORK}/cache.request.json" \
    "${WORK}/cache-1.response.json" \
    "${WORK}/cache-1.headers"
)"
CACHE2_CODE="$(
  request POST \
    "${BASE}/messages" \
    "${WORK}/cache.request.json" \
    "${WORK}/cache-2.response.json" \
    "${WORK}/cache-2.headers"
)"

if [[ "$CACHE1_CODE" == "200" && "$CACHE2_CODE" == "200" ]]; then
  CACHE_CREATED="$(jq -r '.usage.cache_creation_input_tokens // 0' "${WORK}/cache-1.response.json")"
  CACHE_READ="$(jq -r '.usage.cache_read_input_tokens // 0' "${WORK}/cache-2.response.json")"
  printf '       Cache creation tokens: %s\n' "$CACHE_CREATED"
  printf '       Cache read tokens: %s\n' "$CACHE_READ"

  if [[ "$CACHE_READ" =~ ^[0-9]+$ ]] && ((CACHE_READ > 0)); then
    pass 'Prompt cache read observed'
  else
    warn 'Prompt cache request accepted, but no cache read observed'
  fi
else
  fail "Prompt cache requests rejected (HTTP ${CACHE1_CODE}/${CACHE2_CODE})"
fi

jq -n '{
  model: "compat_probe_model_that_must_not_exist_7f39d6",
  max_tokens: 16,
  messages: [{role: "user", content: "Hello"}]
}' >"${WORK}/error.request.json"

ERROR_CODE="$(
  request POST \
    "${BASE}/messages" \
    "${WORK}/error.request.json" \
    "${WORK}/error.response.json" \
    "${WORK}/error.headers"
)"

if [[ "$ERROR_CODE" =~ ^(400|404)$ ]] &&
   jq -e '
     .type == "error" and
     (.error | type == "object") and
     (.error.type | type == "string") and
     (.error.message | type == "string")
   ' "${WORK}/error.response.json" >/dev/null 2>&1; then
  pass 'Anthropic error envelope'
else
  fail "Invalid-model error envelope (HTTP ${ERROR_CODE})"
fi

if [[ "$FULL_1M" == "1" ]]; then
  CONTEXT_WORDS=900000
  warn 'FULL_1M enabled; request may be expensive and only approximates 1M tokens'
else
  CONTEXT_WORDS=50000
fi

python3 - "$CONTEXT_WORDS" <<'PY' >"${WORK}/large-context.txt"
import sys
print("compat " * int(sys.argv[1]))
PY

jq -n \
  --arg model "$MODEL" \
  --rawfile context "${WORK}/large-context.txt" \
  '{
    model: $model,
    max_tokens: 32,
    messages: [{
      role: "user",
      content: [
        {type: "text", text: $context},
        {type: "text", text: "Reply with exactly LARGE_CONTEXT_OK"}
      ]
    }]
  }' >"${WORK}/large-context.request.json"

LARGE_CONTEXT_CODE="$(
  request POST \
    "${BASE}/messages" \
    "${WORK}/large-context.request.json" \
    "${WORK}/large-context.response.json" \
    "${WORK}/large-context.headers"
)"

if [[ "$LARGE_CONTEXT_CODE" == "200" ]] &&
   jq -e '
     .type == "message" and
     (.content | any(.type == "text"))
   ' "${WORK}/large-context.response.json" >/dev/null 2>&1; then
  pass "Large context accepted (${CONTEXT_WORDS} repeated words)"
else
  fail "Large context rejected (${CONTEXT_WORDS} repeated words, HTTP ${LARGE_CONTEXT_CODE})"
fi

if timeout 120s env API_TIMEOUT_MS=60000 \
  claude -p \
    'Reply with exactly CLAUDE_CODE_OK' \
    --output-format json \
    >"${WORK}/claude-basic.json" \
    2>"${WORK}/claude-basic.stderr"; then
  if jq -e '
    .. | strings | select(contains("CLAUDE_CODE_OK"))
  ' "${WORK}/claude-basic.json" >/dev/null 2>&1; then
    pass 'Claude Code basic end-to-end'
  else
    fail 'Claude Code returned JSON but expected text was missing'
  fi
else
  fail 'Claude Code basic end-to-end'
fi

PROBE_FILE="${WORK}/read-probe.txt"
printf 'CLAUDE_TOOL_OK\n' >"$PROBE_FILE"

if timeout 120s env API_TIMEOUT_MS=60000 \
  claude -p \
    "Use Read to read ${PROBE_FILE}, then reply with exact file content and nothing else." \
    --allowedTools Read \
    --output-format json \
    >"${WORK}/claude-read.json" \
    2>"${WORK}/claude-read.stderr"; then
  if jq -e '
    .. | strings | select(contains("CLAUDE_TOOL_OK"))
  ' "${WORK}/claude-read.json" >/dev/null 2>&1; then
    pass 'Claude Code Read tool round trip'
  else
    fail 'Claude Code Read tool ran without expected final content'
  fi
else
  fail 'Claude Code Read tool round trip'
fi

if timeout 120s env API_TIMEOUT_MS=60000 \
  claude -p \
    'Print numbers 1 through 5, one number per line.' \
    --output-format stream-json \
    --verbose \
    >"${WORK}/claude-stream.jsonl" \
    2>"${WORK}/claude-stream.stderr"; then
  if [[ -s "${WORK}/claude-stream.jsonl" ]] &&
     python3 - "${WORK}/claude-stream.jsonl" <<'PY'
import json
import sys

count = 0
with open(sys.argv[1], encoding="utf-8") as handle:
    for line in handle:
        line = line.strip()
        if not line:
            continue
        json.loads(line)
        count += 1

raise SystemExit(0 if count >= 2 else 1)
PY
  then
    pass 'Claude Code stream-json emits valid event lines'
  else
    fail 'Claude Code stream-json output malformed or not streamed'
  fi
else
  fail 'Claude Code stream-json'
fi

PIDS=()
for n in $(seq 1 "$CONCURRENCY"); do
  (
    timeout 120s env API_TIMEOUT_MS=60000 \
      claude -p \
        "Reply with exactly PARALLEL_${n}" \
        --output-format json \
        >"${WORK}/parallel-${n}.json" \
        2>"${WORK}/parallel-${n}.stderr"
  ) &
  PIDS+=("$!")
done

for pid in "${PIDS[@]}"; do
  wait "$pid" || true
done

PARALLEL_OK=1
for n in $(seq 1 "$CONCURRENCY"); do
  if [[ ! -s "${WORK}/parallel-${n}.json" ]] ||
     ! jq -e --arg expected "PARALLEL_${n}" '
       .. | strings | select(contains($expected))
     ' "${WORK}/parallel-${n}.json" >/dev/null 2>&1; then
    PARALLEL_OK=0
    printf '       Parallel request %s failed\n' "$n"
    if grep -qiE '429|rate.?limit' "${WORK}/parallel-${n}.stderr" 2>/dev/null; then
      printf '       Parallel request %s hit rate limit\n' "$n"
    fi
  fi
done

if [[ "$PARALLEL_OK" == "1" ]]; then
  pass "${CONCURRENCY} parallel Claude Code requests"
else
  fail "${CONCURRENCY} parallel Claude Code requests"
fi

{
  printf '\n============================================================\n'
  printf 'Compatibility summary\n'
  printf '============================================================\n'
  printf 'PASS: %s\n' "$PASS"
  printf 'WARN: %s\n' "$WARN"
  printf 'FAIL: %s\n' "$FAIL"
  printf 'Artifacts: %s\n' "$WORK"
  printf 'Configured API model: %s\n' "$MODEL"

  if ((FAIL == 0)); then
    printf 'Verdict: practical Claude Code compatibility PASS\n'
    if [[ "$FULL_1M" != "1" ]]; then
      printf 'Note: real 1M-token context was not tested. Run with FULL_1M=1 only if cost is acceptable.\n'
    fi
  else
    printf 'Verdict: NOT fully compatible; inspect failed artifacts.\n'
  fi
} | tee "$REPORT"

printf '\nImportant files:\n'
printf '  %s\n' "$REPORT"
printf '  %s\n' "${WORK}/basic.response.json"
printf '  %s\n' "${WORK}/tool.response.json"
printf '  %s\n' "${WORK}/tool-result.response.json"
printf '  %s\n' "${WORK}/stream.response.sse"
printf '  %s\n' "${WORK}/thinking.response.json"
printf '  %s\n' "${WORK}/cache-2.response.json"
printf '  %s\n' "${WORK}/error.response.json"
printf '  %s\n' "${WORK}/claude-read.json"
printf '  %s\n' "${WORK}/claude-read.stderr"

exit "$FAIL"
