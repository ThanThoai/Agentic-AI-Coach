#!/usr/bin/env bash
# Blocks file writes/edits that contain hardcoded secrets.
# Triggered by Claude Code on PostToolUse for Write and Edit tools.
#
# Input (stdin): JSON with tool name and input/output details
# Exit 0 = allow, exit 2 = block (Claude sees stdout as the reason)

set -euo pipefail

# Read the hook event JSON from stdin
INPUT=$(cat)

# Only act on Write and Edit tool uses
TOOL_NAME=$(echo "$INPUT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('tool_name',''))" 2>/dev/null || echo "")

if [[ "$TOOL_NAME" != "Write" && "$TOOL_NAME" != "Edit" ]]; then
  exit 0
fi

# Extract the file content being written
FILE_CONTENT=$(echo "$INPUT" | python3 -c "
import sys, json
d = json.load(sys.stdin)
inp = d.get('tool_input', {})
# Write tool uses 'content', Edit uses 'new_string'
content = inp.get('content', '') or inp.get('new_string', '')
print(content)
" 2>/dev/null || echo "")

FILE_PATH=$(echo "$INPUT" | python3 -c "
import sys, json
d = json.load(sys.stdin)
inp = d.get('tool_input', {})
print(inp.get('file_path', '') or inp.get('path', ''))
" 2>/dev/null || echo "")

# Skip binary files, lockfiles, and non-source files
if [[ "$FILE_PATH" =~ \.(png|jpg|jpeg|gif|ico|woff|woff2|ttf|eot|pdf|zip|tar|gz)$ ]]; then
  exit 0
fi
if [[ "$FILE_PATH" =~ (uv\.lock|pnpm-lock\.yaml|package-lock\.json|yarn\.lock)$ ]]; then
  exit 0
fi

FOUND_SECRETS=()

# --- Pattern checks ---

# AWS keys
if echo "$FILE_CONTENT" | grep -qE 'AKIA[0-9A-Z]{16}'; then
  FOUND_SECRETS+=("AWS Access Key ID (AKIA...)")
fi

# Generic secret/password assignments
if echo "$FILE_CONTENT" | grep -qiE '(password|passwd|secret|api_key|apikey|auth_token|access_token|private_key)\s*=\s*["\x27][^"\x27$\{][^"\x27]{6,}["\x27]'; then
  FOUND_SECRETS+=("Hardcoded credential assignment")
fi

# Anthropic API key
if echo "$FILE_CONTENT" | grep -qE 'sk-ant-[a-zA-Z0-9\-_]{20,}'; then
  FOUND_SECRETS+=("Anthropic API key (sk-ant-...)")
fi

# OpenAI API key
if echo "$FILE_CONTENT" | grep -qE 'sk-[a-zA-Z0-9]{20,}'; then
  FOUND_SECRETS+=("OpenAI-style API key (sk-...)")
fi

# JWT secret assigned literally
if echo "$FILE_CONTENT" | grep -qiE 'jwt_secret\s*=\s*["\x27][^"\x27$\{]{8,}["\x27]'; then
  FOUND_SECRETS+=("JWT secret hardcoded")
fi

# Database URL with embedded credentials
if echo "$FILE_CONTENT" | grep -qE 'postgresql(\+asyncpg)?://[^:]+:[^@$\{][^@]+@'; then
  FOUND_SECRETS+=("Database URL with embedded password")
fi

# Private key block
if echo "$FILE_CONTENT" | grep -qE '\-\-\-\-\-BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY\-\-\-\-\-'; then
  FOUND_SECRETS+=("PEM private key block")
fi

# .env file content being written to a non-.env path
if [[ "$FILE_PATH" != *".env"* && "$FILE_PATH" != *".env.example"* ]]; then
  if echo "$FILE_CONTENT" | grep -qE '^[A-Z_]+=.{8,}$' && echo "$FILE_CONTENT" | grep -qiE '(KEY|SECRET|TOKEN|PASSWORD)='; then
    FOUND_SECRETS+=("Possible .env-style secrets written to non-.env file")
  fi
fi

# --- Report ---

if [[ ${#FOUND_SECRETS[@]} -gt 0 ]]; then
  echo "SECRET SCAN BLOCKED: Potential secrets detected in $FILE_PATH"
  echo ""
  echo "Issues found:"
  for secret in "${FOUND_SECRETS[@]}"; do
    echo "  - $secret"
  done
  echo ""
  echo "Fix: Use environment variables and load via pydantic-settings Settings class."
  echo "See .claude/rules/security.md §1 for the secrets policy."
  exit 2
fi

exit 0
