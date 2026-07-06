# LLM API Rotator

> A featherweight, zero-dependency OpenAI-compatible adapter that automatically rotates across LLM APIs when daily quota is exhausted.

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache--2.0-blue.svg)](LICENSE)
[![Research Use Only](https://img.shields.io/badge/Research-Use%20Only-red.svg)](#)
[![Dependencies: 0](https://img.shields.io/badge/dependencies-0-brightgreen.svg)](#)
[![Lines: ~500](https://img.shields.io/badge/lines-~500-lightgrey.svg)](#)

**Single file. Zero pip install. Zero database. Zero configuration beyond a JSON list of providers.**

```bash
python3 scripts/llm_api_rotator.py \
  --config providers.json \
  --prompt "Hello!"
```

---

## ✨ Features

| Feature | Description |
|:--------|:------------|
| **🧘 Zero dependencies** | Pure Python stdlib — `urllib` + `http.server` only. No pip, no venv, no Docker. |
| **🏠 Local-only** | Designed for local/private deployment. Not intended for public-facing services. |
| **🪶 Single file** | ~500 lines of readable Python. Easy to audit, patch, or embed. |
| **🔄 Auto rotation** | Detects quota exhaustion (HTTP 402/403/429 + keyword matching) and switches to the next provider transparently. |
| **🖥️ Two modes** | One-shot CLI for scripting, or persistent forwarding server for any OpenAI-compatible client. |
| **🔑 Env-safe tokens** | `api_token_env` keeps keys out of committed files. |
| **🧵 Thread-safe server** | Lightweight HTTP server with `ThreadingHTTPServer` for concurrent requests. |
| **⏰ TTL cooldown** | Quota-exhausted providers are skipped for a configurable duration (default 24h). |
| **🔄 OpenAI-compatible** | Works with every provider that exposes `POST {base_url}/chat/completions`. |
| **🏷️ Stable model name** | Server mode exposes one fixed model name to clients — backend routing is invisible. |

---

## 🆚 LLM API Rotator vs LiteLLM

Both solve the problem of routing to multiple LLM providers, but at very different scales.

| Aspect | **LLM API Rotator** | **LiteLLM** |
|:-------|:--------------------|:------------|
| **Codebase** | ~500 lines, single file | 100K+ lines, multi-module |
| **Dependencies** | **Zero** (stdlib only) | 20+ pip packages |
| **Install** | `git clone` → run | `pip install litellm[proxy]` + optional Docker |
| **State storage** | In-memory dict (volatile) | SQLite / PostgreSQL + Redis |
| **Streaming** | ❌ Not supported | ✅ Native support |
| **Tool calling** | ❌ Not supported | ✅ Full function calling |
| **Spend tracking** | ❌ Not needed | ✅ Per-request cost tracking |
| **Virtual keys** | ❌ Not needed (personal use) | ✅ Multi-tenant API key management |
| **Configuration** | Single JSON file | YAML + database + env vars |
| **Database migrations** | ❌ None | Prisma ORM with migrations |
| **Caching** | ❌ None | Redis / local / S3 / GCS |
| **Startup time** | Instant | 5-30s (DB init + migrations) |
| **Best for** | Personal use with multiple APIs | Enterprise, production, paid APIs |

### 🎯 When to use LLM API Rotator

You're in the right place if:

- **You want to rotate across multiple APIs** (DeepSeek, GLM, Kimi, etc.) with auto-failover when daily quota runs out
- **You don't need streaming** — your use case is chat completion, summarization, classification
- **You want dead-simple local deployment** — no Docker, no DB, no Redis, no migrations, no config heroics
- **You're running on a low-resource machine** — the process uses ~10MB RAM and ~0% CPU when idle
- **You want to audit every line of code** — 500 lines, pure Python, no compiled extensions
- **You want a single-file embeddable solution** — drop `llm_api_rotator.py` into any project and go

### 🏭 When to use LiteLLM

LiteLLM is the better choice if:

- **You need streaming** for real-time chat or agentic tool calls
- **You need tool calling / function calling** for structured LLM interactions
- **You're spending real money** and need cost tracking, budgets, and rate limits
- **You run a multi-tenant service** with virtual API keys, user management, and audit logs
- **You need production-grade reliability** with Redis-backed cooldowns, Prometheus metrics, and health checks
- **You deploy on Kubernetes** and need health probes, graceful shutdowns, and horizontal scaling

> **In short:** LLM API Rotator is a ~500-line stdlib script for personal use. LiteLLM is a 100K+ line enterprise proxy. Pick the one that matches your complexity budget.

---

## 🚀 Quick Start

### 1. Provider config

Create `providers.json`:

```json
{
  "providers": [
    {
      "name": "deepseek",
      "base_url": "https://api.deepseek.com/v1",
      "api_token_env": "DEEPSEEK_API_KEY",
      "model": "deepseek-chat"
    },
    {
      "name": "glm",
      "base_url": "https://open.bigmodel.cn/api/paas/v4",
      "api_token_env": "GLM_API_KEY",
      "model": "glm-4-flash"
    },
    {
      "name": "kimi",
      "base_url": "https://api.moonshot.cn/v1",
      "api_token_env": "KIMI_API_KEY",
      "model": "moonshot-v1-8k"
    }
  ]
}
```

Set your tokens in the environment:

```bash
export DEEPSEEK_API_KEY="sk-..."
export GLM_API_KEY="..."
export KIMI_API_KEY="..."
```

### 2. Run a one-shot prompt

```bash
python3 scripts/llm_api_rotator.py \
  --config providers.json \
  --prompt "Write a haiku about LLMs"
```

Stdout gets the assistant reply, stderr gets which provider was used:

```text
used_provider=deepseek
```

If the first provider is exhausted, it automatically retries with the next one — no client changes needed.

### 3. Run as a local server

```bash
python3 scripts/llm_api_rotator.py \
  --config providers.json \
  --serve \
  --host 127.0.0.1 \
  --port 8000 \
  --local-model local-rotator
```

The server prints a temporary local API key. Point any OpenAI-compatible client at:

```
Base URL: http://127.0.0.1:8000/v1
Model:    local-rotator
API key:  <printed-on-startup>
```

---

## 📖 CLI Reference

### Options

| Flag | Default | Description |
|:-----|:--------|:------------|
| `--config` | *(required)* | Path to provider JSON config |
| `--prompt` | — | Single user prompt |
| `--messages` | — | OpenAI-format messages JSON array |
| `--temperature` | `0.7` | Sampling temperature |
| `--max-tokens` | — | Max output tokens |
| `--timeout` | `60` | HTTP request timeout (seconds) |
| `--retry-sleep` | `0` | Sleep before rotating after non-quota failures |
| `--raw` | — | Print full JSON response instead of just the message |
| `--serve` | — | Run as a local forwarding server |
| `--host` | `127.0.0.1` | Server bind host |
| `--port` | `8000` | Server bind port |
| `--local-model` | `local-rotator` | Stable model name advertised to clients |
| `--local-api-key` | *(random)* | Local bearer token for the server |
| `--local-api-key-env` | — | Read local bearer token from an env var |
| `--exhaustion-ttl-seconds` | `86400` | How long to skip quota-exhausted providers |

### Server mode endpoints

| Endpoint | Description |
|:---------|:------------|
| `GET /health` | Health check + rotator snapshot |
| `GET /v1/models` | List available models (OpenAI-compatible) |
| `POST /v1/chat/completions` | Chat completion (OpenAI-compatible) |
| `POST /chat/completions` | Alternative path |
| `GET /api/tags` | Ollama-compatible model list |

### Input sources (one-shot mode)

```bash
# Via --prompt
python3 scripts/llm_api_rotator.py --config providers.json --prompt "Hello"

# Via --messages (multi-turn)
python3 scripts/llm_api_rotator.py --config providers.json \
  --messages '[{"role":"system","content":"You are concise."},{"role":"user","content":"Hi"}]'

# Via stdin
printf 'Tell me a joke' | python3 scripts/llm_api_rotator.py --config providers.json
```

---

## 🔄 How Rotation Works

1. Providers are tried **in order** as listed in `providers.json`.
2. The script detects quota exhaustion reactively (not proactively) — it sends the request and watches for error signals:

   - **Status codes:** HTTP `402`, `403`, `429`
   - **Error keywords:** `quota`, `rate limit`, `insufficient_quota`, `billing`, `credit`, `daily limit`, `tokens exhausted`

3. On quota error → marks provider **exhausted** for TTL (default 24h), retries the **same request** with the next provider.
4. On non-quota failure → marks provider **temporarily failed**, tries the next one.
5. In **server mode**, exhausted providers get a TTL cooldown (`--exhaustion-ttl-seconds`). Non-quota failures don't trigger cooldown — they advance the index and the provider will be retried on the next request.
6. If **all** providers fail, an error is returned.

### Server mode request lifecycle

```text
Client sends:    model = local-rotator
Server tries:    provider-a / backend-model-a
Quota error:     provider-a is skipped (24h cooldown)
Server retries:  provider-b / backend-model-b
Client sees:     model = local-rotator (unchanged)
```

---

## ⚠️ Limitations

- **No streaming** — `stream: true` is silently converted to `false` in server mode
- **No tool/function calling** — pure chat completions only
- **No token counting** — the script doesn't know remaining quota until it tries
- **Single stable model name** — server mode exposes one local model to all clients
- **Reactive exhaustion detection** — quota is only detected when a request actually fails
- **In-memory state** — restarting the server resets all cooldown state (which is fine for daily-reset quota)

---

## 🔒 Security Notes

- **Never commit API tokens.** Use `api_token_env` in your config and export the real key as an environment variable.
- The local API key (`--local-api-key`) is **only for client-to-server auth** — upstream provider keys still come from the config file.
- The local API key changes every server start unless you set `--local-api-key` or `--local-api-key-env`.

---

## 📄 License & Notices

Apache-2.0 — see [LICENSE](LICENSE).

🔬 Research Use Only — This software is provided for research, educational, and personal use only. Commercial use, production deployment, or revenue-generating use requires explicit permission.

🏠 Local Deployment Only — This tool is designed for local/private use. Do not deploy as a public-facing service.

🤖 AI-Assisted Authorship — This project was created with the assistance of AI coding agents.
