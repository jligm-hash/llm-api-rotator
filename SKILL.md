# LLM API Rotator Skill

Use this skill when the user wants to configure multiple OpenAI-compatible LLM API endpoints and automatically rotate between models when a provider reports that the free daily token quota is exhausted.

## What this skill provides

- A Python OpenAI-format adapter script at `scripts/llm_api_rotator.py`.
- Reads provider/model entries from a JSON config file.
- Sends one-shot chat-completion requests using the OpenAI-compatible `/chat/completions` format.
- Runs a local OpenAI-compatible forwarding server with a stable local model name.
- Rotates to the next configured model when quota/rate-limit/token-exhaustion errors occur.
- Stops only after all configured model quotas appear exhausted or all endpoints fail.

## Expected config

Create a JSON file like this:

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

You can also omit `api_token` and use an environment variable instead:

```json
{
  "providers": [
    {
      "name": "provider-a",
      "base_url": "https://example.com/v1",
      "api_token_env": "PROVIDER_A_API_KEY",
      "model": "free-model-a"
    }
  ]
}
```

## Usage

```bash
python scripts/llm_api_rotator.py --config providers.json --prompt "Say hello"
```

For multi-turn chat, pass messages as JSON:

```bash
python scripts/llm_api_rotator.py --config providers.json --messages '[{"role":"user","content":"Say hello"}]'
```

For a stable local OpenAI-compatible server:

```bash
python scripts/llm_api_rotator.py \
  --config providers.json \
  --serve \
  --host 127.0.0.1 \
  --port 8000 \
  --local-model local-rotator
```

The server prints a temporary local API key on startup. Then configure OpenAI-compatible clients with:

```text
Base URL: http://127.0.0.1:8000/v1
Model: local-rotator
API key: <generated-local-api-key>
```

The base URL can stay stable while the local key changes each time the server starts. Use `--local-api-key-env ENV_NAME` if the user wants to provide the local key without putting it in command history.

## Notes

- The script does not know the exact free-token balance in advance. It detects quota exhaustion from common HTTP status codes and error text, then rotates.
- Keep API tokens out of committed files. Prefer `api_token_env` for real usage.
- Providers must support the OpenAI-compatible chat-completions API.
