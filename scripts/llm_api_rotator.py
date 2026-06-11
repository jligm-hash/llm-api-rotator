#!/usr/bin/env python3
"""Rotate across OpenAI-compatible LLM APIs when free daily quota is exhausted."""

import argparse
import json
import os
import secrets
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


QUOTA_STATUS_CODES = {402, 403, 429}
QUOTA_ERROR_HINTS = (
    "quota",
    "rate limit",
    "rate_limit",
    "too many requests",
    "insufficient_quota",
    "billing",
    "credit",
    "credits",
    "free tier",
    "daily limit",
    "token limit",
    "tokens exhausted",
)
CHAT_COMPLETION_PATHS = {"/v1/chat/completions", "/chat/completions"}


@dataclass
class Provider:
    name: str
    base_url: str
    api_token: str
    model: str


class ProviderFailed(Exception):
    def __init__(self, message: str, quota_exhausted: bool = False):
        super().__init__(message)
        self.quota_exhausted = quota_exhausted


class RotatorState:
    def __init__(self, providers: list[Provider], exhaustion_ttl_seconds: float):
        self.providers = providers
        self.exhaustion_ttl_seconds = exhaustion_ttl_seconds
        self.current_index = 0
        self.exhausted_until: dict[str, float] = {}
        self.lock = threading.Lock()

    def clear_expired_exhaustion(self) -> None:
        now = time.time()
        expired = [name for name, until in self.exhausted_until.items() if until <= now]
        for name in expired:
            del self.exhausted_until[name]

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            self.clear_expired_exhaustion()
            return {
                "providers": len(self.providers),
                "current_provider": self.providers[self.current_index].name,
                "exhausted": sorted(self.exhausted_until),
            }

    def chat_completion(self, payload: dict[str, Any], timeout: int, local_model: str) -> tuple[Provider, dict[str, Any]]:
        failures = []
        temporarily_failed = set()

        while True:
            with self.lock:
                self.clear_expired_exhaustion()
                available = [
                    index
                    for index, provider in enumerate(self.providers)
                    if provider.name not in self.exhausted_until and provider.name not in temporarily_failed
                ]
                if not available:
                    break
                if self.current_index not in available:
                    self.current_index = available[0]
                provider = self.providers[self.current_index]

            try:
                response = request_openai_compatible(provider, payload, timeout)
            except ProviderFailed as error:
                failures.append(str(error))
                with self.lock:
                    if error.quota_exhausted:
                        self.exhausted_until[provider.name] = time.time() + self.exhaustion_ttl_seconds
                        print(f"quota exhausted, rotating from {provider.name}", file=sys.stderr)
                    else:
                        temporarily_failed.add(provider.name)
                        print(f"temporary failure on {provider.name}: {error}", file=sys.stderr)
                    self._advance_from_locked(provider.name)
                continue

            with self.lock:
                self.current_index = self.providers.index(provider)
            if isinstance(response.get("model"), str):
                response["model"] = local_model
            return provider, response

        raise RuntimeError("all providers failed or exhausted:\n" + "\n".join(failures))

    def _advance_from_locked(self, provider_name: str) -> None:
        for index, provider in enumerate(self.providers):
            if provider.name == provider_name:
                self.current_index = (index + 1) % len(self.providers)
                return


def load_config(path: str) -> list[Provider]:
    with open(path, "r", encoding="utf-8") as file:
        raw = json.load(file)

    providers = []
    for index, item in enumerate(raw.get("providers", []), start=1):
        name = item.get("name") or f"provider-{index}"
        token = item.get("api_token")
        token_env = item.get("api_token_env")
        if not token and token_env:
            token = os.environ.get(token_env)
        if not token:
            raise ValueError(f"{name}: missing api_token or api_token_env")
        if not item.get("base_url"):
            raise ValueError(f"{name}: missing base_url")
        if not item.get("model"):
            raise ValueError(f"{name}: missing model")
        providers.append(
            Provider(
                name=name,
                base_url=item["base_url"].rstrip("/"),
                api_token=token,
                model=item["model"],
            )
        )

    if not providers:
        raise ValueError("config must include at least one provider")
    return providers


def is_quota_error(status_code: int | None, body: str) -> bool:
    lowered = body.lower()
    return status_code in QUOTA_STATUS_CODES or any(hint in lowered for hint in QUOTA_ERROR_HINTS)


def request_openai_compatible(provider: Provider, payload: dict[str, Any], timeout: int) -> dict[str, Any]:
    url = f"{provider.base_url}/chat/completions"
    upstream_payload = dict(payload)
    upstream_payload["model"] = provider.model
    data = json.dumps(upstream_payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {provider.api_token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        raise ProviderFailed(
            f"{provider.name} returned HTTP {error.code}: {body}",
            quota_exhausted=is_quota_error(error.code, body),
        ) from error
    except urllib.error.URLError as error:
        raise ProviderFailed(f"{provider.name} request failed: {error}") from error
    except OSError as error:
        raise ProviderFailed(f"{provider.name} request failed: {error}") from error
    except json.JSONDecodeError as error:
        raise ProviderFailed(f"{provider.name} returned invalid JSON: {error}") from error


def request_chat_completion(
    provider: Provider,
    messages: list[dict[str, str]],
    temperature: float,
    max_tokens: int | None,
    timeout: int,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": provider.model,
        "messages": messages,
        "temperature": temperature,
    }
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    return request_openai_compatible(provider, payload, timeout)


def rotate_until_success(
    providers: list[Provider],
    messages: list[dict[str, str]],
    temperature: float,
    max_tokens: int | None,
    timeout: int,
    retry_sleep: float,
) -> tuple[Provider, dict[str, Any]]:
    exhausted = set()
    failures = []

    while len(exhausted) < len(providers):
        progressed = False
        for provider in providers:
            if provider.name in exhausted:
                continue
            progressed = True
            try:
                return provider, request_chat_completion(
                    provider=provider,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout=timeout,
                )
            except ProviderFailed as error:
                failures.append(str(error))
                if error.quota_exhausted:
                    exhausted.add(provider.name)
                    print(f"quota exhausted, rotating from {provider.name}", file=sys.stderr)
                else:
                    print(f"temporary failure on {provider.name}: {error}", file=sys.stderr)
                    if retry_sleep > 0:
                        time.sleep(retry_sleep)
                    exhausted.add(provider.name)
        if not progressed:
            break

    raise RuntimeError("all providers failed or exhausted:\n" + "\n".join(failures))


def parse_messages(args: argparse.Namespace) -> list[dict[str, str]]:
    if args.messages:
        messages = json.loads(args.messages)
        if not isinstance(messages, list):
            raise ValueError("--messages must be a JSON list")
        return messages
    if args.prompt:
        return [{"role": "user", "content": args.prompt}]
    if not sys.stdin.isatty():
        return [{"role": "user", "content": sys.stdin.read()}]
    raise ValueError("provide --prompt, --messages, or stdin")


def openai_error(message: str, error_type: str, code: str | None = None) -> dict[str, Any]:
    error: dict[str, Any] = {"message": message, "type": error_type}
    if code:
        error["code"] = code
    return {"error": error}


def make_handler(state: RotatorState, local_model: str, timeout: int, local_api_key: str):
    class RotatorRequestHandler(BaseHTTPRequestHandler):
        server_version = "LLMApiRotator/1.0"

        def do_GET(self) -> None:
            if self.path == "/health":
                self.write_json(200, {"ok": True, "local_model": local_model, **state.snapshot()})
                return
            if self.path in {"/version", "/v1/version"}:
                self.write_json(200, {"version": "llm-api-rotator", "local_model": local_model})
                return
            if self.path in {"/props", "/v1/props"}:
                self.write_json(200, {"models": [local_model], "chat_completions": True})
                return
            if self.path in {"/v1/models", "/api/v1/models"}:
                if not self.check_local_auth():
                    return
                self.write_json(200, self.openai_models_response())
                return
            if self.path == f"/v1/models/{local_model}":
                if not self.check_local_auth():
                    return
                self.write_json(200, self.openai_model_response())
                return
            if self.path == "/api/tags":
                if not self.check_local_auth():
                    return
                self.write_json(200, self.ollama_tags_response())
                return
            self.write_json(404, openai_error("not found", "invalid_request_error", "not_found"))

        def do_POST(self) -> None:
            if self.path == "/api/show":
                if not self.check_local_auth():
                    return
                self.write_json(200, self.ollama_show_response())
                return
            if self.path not in CHAT_COMPLETION_PATHS:
                self.write_json(404, openai_error("not found", "invalid_request_error", "not_found"))
                return
            if not self.check_local_auth():
                return

            payload = self.read_json_body()
            if payload is None:
                return
            if not isinstance(payload, dict):
                self.write_json(400, openai_error("request body must be a JSON object", "invalid_request_error"))
                return
            if payload.get("stream") is True:
                payload = dict(payload)
                payload["stream"] = False

            try:
                provider, response = state.chat_completion(payload, timeout, local_model)
            except RuntimeError as error:
                self.write_json(
                    503,
                    openai_error(str(error), "rotator_exhausted", "all_providers_exhausted"),
                )
                return

            self.write_json(
                200,
                response,
                {
                    "X-Rotator-Provider": provider.name,
                    "X-Rotator-Upstream-Model": provider.model,
                },
            )

        def openai_model_response(self) -> dict[str, Any]:
            return {"id": local_model, "object": "model", "owned_by": "llm-api-rotator"}

        def openai_models_response(self) -> dict[str, Any]:
            return {"object": "list", "data": [self.openai_model_response()]}

        def ollama_tags_response(self) -> dict[str, Any]:
            return {
                "models": [
                    {
                        "name": local_model,
                        "model": local_model,
                        "modified_at": "1970-01-01T00:00:00Z",
                        "size": 0,
                        "digest": "llm-api-rotator",
                        "details": {"family": "openai-compatible", "parameter_size": "unknown", "quantization_level": "unknown"},
                    }
                ]
            }

        def ollama_show_response(self) -> dict[str, Any]:
            return {
                "license": "",
                "modelfile": f"FROM {local_model}",
                "parameters": "",
                "template": "",
                "details": {"family": "openai-compatible", "parameter_size": "unknown", "quantization_level": "unknown"},
                "model_info": {"name": local_model},
            }

        def check_local_auth(self) -> bool:
            expected = f"Bearer {local_api_key}"
            if self.headers.get("Authorization") == expected:
                return True
            self.write_json(
                401,
                openai_error("missing or invalid local API key", "authentication_error", "invalid_local_api_key"),
            )
            return False

        def read_json_body(self) -> Any | None:
            try:
                content_length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                self.write_json(400, openai_error("invalid Content-Length", "invalid_request_error"))
                return None
            body = self.rfile.read(content_length)
            try:
                return json.loads(body.decode("utf-8"))
            except json.JSONDecodeError:
                self.write_json(400, openai_error("request body must be valid JSON", "invalid_request_error"))
                return None

        def write_json(self, status: int, payload: dict[str, Any], headers: dict[str, str] | None = None) -> None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            if headers:
                for name, value in headers.items():
                    self.send_header(name, value)
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format: str, *args: Any) -> None:
            print(f"{self.address_string()} - {format % args}", file=sys.stderr)

    return RotatorRequestHandler


def serve(
    providers: list[Provider],
    host: str,
    port: int,
    local_model: str,
    timeout: int,
    exhaustion_ttl_seconds: float,
    local_api_key: str,
) -> None:
    state = RotatorState(providers, exhaustion_ttl_seconds)
    handler = make_handler(state, local_model, timeout, local_api_key)
    server = ThreadingHTTPServer((host, port), handler)
    print(f"serving local OpenAI-compatible rotator at http://{host}:{port}/v1", file=sys.stderr)
    print(f"local_model={local_model}", file=sys.stderr)
    print(f"local_api_key={local_api_key}", file=sys.stderr)
    print("local_api_key is only for this local server; upstream provider keys still come from config", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("server stopped", file=sys.stderr)
    finally:
        server.server_close()


def resolve_local_api_key(args: argparse.Namespace) -> str:
    if args.local_api_key:
        return args.local_api_key
    if args.local_api_key_env:
        value = os.environ.get(args.local_api_key_env)
        if not value:
            raise ValueError(f"{args.local_api_key_env}: environment variable is not set")
        return value
    return secrets.token_urlsafe(32)


def main() -> int:
    parser = argparse.ArgumentParser(description="OpenAI-compatible LLM API rotator")
    parser.add_argument("--config", required=True, help="path to provider JSON config")
    parser.add_argument("--prompt", help="single user prompt")
    parser.add_argument("--messages", help="OpenAI-format messages JSON")
    parser.add_argument("--temperature", type=float, default=0.7)
    parser.add_argument("--max-tokens", type=int)
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--retry-sleep", type=float, default=0)
    parser.add_argument("--raw", action="store_true", help="print full JSON response")
    parser.add_argument("--serve", action="store_true", help="run a local OpenAI-compatible forwarding server")
    parser.add_argument("--host", default="127.0.0.1", help="server host for --serve")
    parser.add_argument("--port", type=int, default=8000, help="server port for --serve")
    parser.add_argument("--local-model", default="local-rotator", help="stable model name advertised by --serve")
    parser.add_argument("--local-api-key", help="local bearer token required by --serve for this run")
    parser.add_argument("--local-api-key-env", help="environment variable containing the local bearer token for --serve")
    parser.add_argument(
        "--exhaustion-ttl-seconds",
        type=float,
        default=86400,
        help="seconds to skip quota-exhausted providers in --serve mode",
    )
    args = parser.parse_args()

    try:
        providers = load_config(args.config)
        if args.serve:
            serve(
                providers=providers,
                host=args.host,
                port=args.port,
                local_model=args.local_model,
                timeout=args.timeout,
                exhaustion_ttl_seconds=args.exhaustion_ttl_seconds,
                local_api_key=resolve_local_api_key(args),
            )
            return 0

        messages = parse_messages(args)
        provider, response = rotate_until_success(
            providers=providers,
            messages=messages,
            temperature=args.temperature,
            max_tokens=args.max_tokens,
            timeout=args.timeout,
            retry_sleep=args.retry_sleep,
        )
    except Exception as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    print(f"used_provider={provider.name}", file=sys.stderr)
    if args.raw:
        print(json.dumps(response, ensure_ascii=False, indent=2))
    else:
        choices = response.get("choices") or []
        if not choices:
            print(json.dumps(response, ensure_ascii=False))
        else:
            print(choices[0].get("message", {}).get("content", ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
