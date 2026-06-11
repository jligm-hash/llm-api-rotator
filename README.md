# LLM API Rotator

A small OpenAI-compatible adapter that sends chat-completion requests to a list of free-tier LLM models and automatically switches to the next model when the current one appears to run out of daily free tokens.

## Files

- `SKILL.md` — Claude Code skill instructions.
- `scripts/llm_api_rotator.py` — Python script for OpenAI-format chat completions with provider rotation.
- `README.md` — this usage guide.
- `usage.html` — browser-friendly usage guide.

## Requirements

- Python 3.10+.
- No third-party Python packages are required.
- Each provider must expose an OpenAI-compatible endpoint: `POST {base_url}/chat/completions`.

In this Claude Code environment, the configured Python is available as:

```bash
"$TUMOR_ABM_PYTHON"
```

## 1. Create a provider config

Create a JSON file, for example `providers.json`:

```json
{
  "providers": [
    {
      "name": "provider-a-free-model",
      "base_url": "https://example.com/v1",
      "api_token": "YOUR_TOKEN",
      "model": "free-model-a"
    },
    {
      "name": "provider-b-free-model",
      "base_url": "https://example.org/v1",
      "api_token": "YOUR_OTHER_TOKEN",
      "model": "free-model-b"
    }
  ]
}
```

Required fields per provider:

| Field | Meaning |
| --- | --- |
| `name` | Local label printed when that provider is used or skipped. |
| `base_url` | OpenAI-compatible base URL, usually ending with `/v1`. |
| `api_token` | API key/token for the provider. |
| `model` | Model name sent in the OpenAI-format request body. |

## 2. Prefer environment variables for tokens

Instead of writing API tokens directly into `providers.json`, use `api_token_env`:

```json
{
  "providers": [
    {
      "name": "provider-a-free-model",
      "base_url": "https://example.com/v1",
      "api_token_env": "PROVIDER_A_API_KEY",
      "model": "free-model-a"
    }
  ]
}
```

Then set the variable before running:

```bash
export PROVIDER_A_API_KEY="your-token-here"
```

This is safer than storing tokens in files.

## 3. Run a single prompt

From the `./skills` folder:

```bash
"$TUMOR_ABM_PYTHON" llm-api-rotator/scripts/llm_api_rotator.py \
  --config providers.json \
  --prompt "Say hello in one sentence"
```

The assistant text is printed to stdout. The selected provider is printed to stderr:

```text
used_provider=provider-a-free-model
```

## 4. Run with OpenAI-format messages

Use `--messages` for multi-turn input:

```bash
"$TUMOR_ABM_PYTHON" llm-api-rotator/scripts/llm_api_rotator.py \
  --config providers.json \
  --messages '[{"role":"system","content":"You are concise."},{"role":"user","content":"Explain APIs."}]'
```

## 5. Pipe prompt text from stdin

```bash
printf 'Write a short haiku about GPUs' | \
"$TUMOR_ABM_PYTHON" llm-api-rotator/scripts/llm_api_rotator.py \
  --config providers.json
```

## 6. Print the raw JSON response

```bash
"$TUMOR_ABM_PYTHON" llm-api-rotator/scripts/llm_api_rotator.py \
  --config providers.json \
  --prompt "Return a JSON greeting" \
  --raw
```

## 7. Useful options

```bash
--temperature 0.2     # Sampling temperature, default 0.7
--max-tokens 512      # Optional output token cap
--timeout 60          # HTTP timeout in seconds, default 60
--retry-sleep 2       # Sleep before rotating after non-quota failures
--raw                 # Print the full JSON response
```

## 8. Run as a local OpenAI-compatible server

Use server mode when you want clients to keep one stable local base URL and model name while this script rotates upstream provider model names internally.

```bash
"$TUMOR_ABM_PYTHON" llm-api-rotator/scripts/llm_api_rotator.py \
  --config providers.json \
  --serve \
  --host 127.0.0.1 \
  --port 8000 \
  --local-model local-rotator
```

When the server starts, it prints a temporary local API key for this run:

```text
serving local OpenAI-compatible rotator at http://127.0.0.1:8000/v1
local_model=local-rotator
local_api_key=<generated-local-api-key>
```

Point any OpenAI-compatible client at:

```text
Base URL: http://127.0.0.1:8000/v1
Model: local-rotator
API key: <generated-local-api-key>
```

The base URL can stay permanent, but the local API key changes each time the server starts unless you explicitly provide one with `--local-api-key` or `--local-api-key-env`. This local key only protects client-to-local-server requests; real upstream provider tokens still come from `providers.json` or `api_token_env`.

Backend token exhaustion is checked reactively when a client request arrives. The server does not check token balances ahead of time; instead, it forwards the request to the current backend model and watches for quota/free-token errors such as HTTP `402`, `403`, `429`, or quota-related error text. When one backend model is used up, the server marks that provider exhausted, retries the same client request with the next provider model, and keeps the client-facing model name unchanged.

```text
Client sends:    model = local-rotator
Server tries:    provider-a / backend-model-a
Quota error:     provider-a is skipped
Server retries:  provider-b / backend-model-b
Client sees:     model = local-rotator
```

By default, server mode skips a quota-exhausted provider for 24 hours:

```bash
--exhaustion-ttl-seconds 86400
```

Lower this value if your provider resets quota sooner, or increase it if the reset window is longer.

Example request:

```bash
curl http://127.0.0.1:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <generated-local-api-key>" \
  -d '{"model":"local-rotator","messages":[{"role":"user","content":"Say hello"}],"stream":false}'
```

Useful server endpoints:

```text
GET  /health
GET  /v1/models
POST /v1/chat/completions
POST /chat/completions
```

Server options:

```bash
--serve                         # Start local forwarding server
--host 127.0.0.1                # Server bind host
--port 8000                     # Server port
--local-model local-rotator     # Stable model name clients use
--local-api-key KEY             # Optional local key for this server run
--local-api-key-env ENV_NAME    # Read the local key from an environment variable
--exhaustion-ttl-seconds 86400  # How long to skip quota-exhausted providers
```

Server mode accepts any incoming model name, replaces it with the selected upstream provider's configured `model`, and rewrites the response `model` field back to the local model name when present. It does not support streaming yet; send `"stream": false` or omit `stream`.

## CLI model setting formats

These examples show how to point common coding-agent CLIs at Haiku 4.5 or add an alias for it. Use the provider/model identifier required by your account or gateway if it differs.

### Claude Code CLI

User-wide settings file:

```text
~/.claude/settings.json
```

Project settings file:

```text
.claude/settings.json
```

Settings JSON:

```json
{
  "model": "haiku"
}
```

### OpenClaw

Set the default model from the CLI:

```bash
openclaw models set anthropic/claude-haiku-4-5-20251001
```

Equivalent config shape:

```json
{
  "agents": {
    "defaults": {
      "model": {
        "primary": "anthropic/claude-haiku-4-5-20251001",
        "fallbacks": []
      }
    }
  }
}
```

### Hermes Agent

Settings file:

```text
~/.hermes/config.yaml
```

Model config:

```yaml
model:
  provider: anthropic
  name: claude-haiku-4-5-20251001
```

Alias command:

```bash
hermes config set model.aliases.haiku anthropic/claude-haiku-4-5-20251001
```

Interactive model selector:

```bash
hermes model
```

## How rotation works

The script tries providers in the order listed in `providers.json`.

It rotates when an endpoint returns common quota or free-tier exhaustion signals, including:

- HTTP `402`, `403`, or `429`.
- Error text containing phrases like `quota`, `rate limit`, `insufficient_quota`, `billing`, `credit`, `free tier`, `daily limit`, or `tokens exhausted`.

If the first model has used its free daily tokens, the script marks it exhausted and tries the next provider. It continues until one provider succeeds or all providers fail/exhaust.

## Important notes

- The script cannot know each provider's remaining free tokens before making a request.
- Different providers use different quota error messages, so you may need to add more phrases to `QUOTA_ERROR_HINTS` in `scripts/llm_api_rotator.py` for a specific service.
- Do not commit real API tokens. Use `api_token_env` for normal usage.
- This script targets chat completions only: `/chat/completions`.
