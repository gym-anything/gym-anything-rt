"""Qwen35VL's screenshot/action agent over the normal Tinker sampling API."""
from __future__ import annotations

import base64
import gzip
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import time
import uuid

import httpx
from PIL import Image

from gym_anything_rt.agents.qwen35vl import RealTimeQwen35VLAgent


class ContextLengthError(ValueError):
    pass


def retryable(error):
    status = getattr(getattr(error, "response", None), "status_code", None)
    return isinstance(error, (httpx.TransportError, TimeoutError)) or status in (408, 429) or (
        status is not None and 500 <= status <= 599
    )


def reasoning_length(tokens, end_think_token):
    """The generation prompt ends in <think>; count emitted tokens before its end."""
    return tokens.index(end_think_token) if end_think_token in tokens else len(tokens)


class TinkerSampling:
    def __init__(self, *, model, tokenizer_path, base_url, api_key, log_dir,
                 timeout=900, attempts=3):
        from transformers import AutoTokenizer
        from transformers.models.qwen2_vl.image_processing_qwen2_vl import Qwen2VLImageProcessor

        self.model = model
        self.tokenizer = AutoTokenizer.from_pretrained(tokenizer_path, local_files_only=True)
        self.processor = Qwen2VLImageProcessor.from_pretrained(tokenizer_path, local_files_only=True)
        self.client = httpx.Client(base_url=base_url.rstrip("/"), headers={"X-API-Key": api_key},
                                   transport=httpx.HTTPTransport(retries=0))
        self.root = Path(log_dir)
        self.root.mkdir(parents=True, exist_ok=True)
        self.timeout, self.attempts = float(timeout), int(attempts)
        if self.timeout <= 0 or self.attempts < 1:
            raise ValueError("finite timeout and positive total attempts required")
        self.session = None
        self.sampler = None
        self.seq = 0
        self.idempotency_prefix = uuid.uuid4().hex

    def record(self, value):
        with (self.root / "model_calls.jsonl").open("a") as f:
            f.write(json.dumps(value, separators=(",", ":")) + "\n")
            f.flush()
            os.fsync(f.fileno())

    def render(self, messages):
        rendered = self.tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True, enable_thinking=True)
        assert rendered.endswith("<think>\n")
        images = []
        for message in messages:
            if isinstance(message["content"], list):
                for item in message["content"]:
                    if item.get("type") == "image_url":
                        url = item["image_url"]["url"]
                        if not url.startswith(("data:image/png;base64,", "data:image/jpeg;base64,")):
                            raise ValueError("only inline PNG/JPEG screenshots are supported")
                        header, encoded = url.split(",", 1)
                        raw = base64.b64decode(encoded, validate=True)
                        with Image.open(BytesIO(raw)) as image:
                            count = self.processor.get_number_of_image_patches(image.height, image.width, {})
                        images.append(dict(type="image", data=encoded,
                                           format="png" if "image/png" in header else "jpeg",
                                           expected_tokens=int(count) // self.processor.merge_size ** 2))
        parts = rendered.split("<|image_pad|>")
        if len(parts) != len(images) + 1:
            raise ValueError("chat template image positions disagree with supplied screenshots")
        chunks = []
        for index, part in enumerate(parts):
            chunks.append(dict(type="encoded_text", tokens=self.tokenizer.encode(part, add_special_tokens=False)))
            if index < len(images):
                chunks.append(images[index])
        return {"chunks": chunks}

    def _post(self, route, body, deadline):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Tinker model-call deadline exceeded")
        identity = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
        response = self.client.post("/api/v1/" + route, json=body,
                                    headers={"Accept": "application/x-protobuf, application/json",
                                             "X-Idempotency-Key": f"{self.idempotency_prefix}:{route}:{identity}"},
                                    timeout=min(60, remaining))
        if response.is_error:
            raise httpx.HTTPStatusError(f"Tinker {route}: HTTP {response.status_code}: {response.text[:1500]}",
                                        request=response.request, response=response)
        return response

    def sample(self, messages, *, step, temperature, top_p, top_k, max_tokens, image_paths):
        from tinker.proto.response_conv import deserialize_sample_response

        started = time.monotonic()
        deadline = started + self.timeout
        prompt = self.render(messages)
        input_tokens = sum(len(c["tokens"]) if c["type"] == "encoded_text" else c["expected_tokens"]
                           for c in prompt["chunks"])
        if input_tokens + max_tokens > 131072:
            self.record(dict(event="context_variant_skipped", step=step,
                             input_tokens=input_tokens, max_tokens=max_tokens))
            raise ContextLengthError("Tinker prompt exceeds the 131072-token model context")
        params = dict(temperature=temperature, top_p=top_p, top_k=top_k,
                      max_tokens=max_tokens, stop=[self.tokenizer.eos_token_id])
        record = dict(step=step, seq_id=self.seq, model=self.model, model_path=None,
                      started_at_unix=time.time(), input_tokens=input_tokens, sampling=params,
                      total_attempt_limit=self.attempts, deadline_seconds=self.timeout)
        logged_chunks = []
        for chunk in prompt["chunks"]:
            if chunk["type"] == "encoded_text":
                logged_chunks.append(chunk)
            else:
                raw = base64.b64decode(chunk["data"])
                logged_chunks.append({k: v for k, v in chunk.items() if k != "data"} | {
                    "path": image_paths.get(chunk["data"]), "sha256": hashlib.sha256(raw).hexdigest()})
        request_path = self.root / f"request-{self.seq:04d}.json.gz"
        with gzip.open(request_path, "wt") as f:
            json.dump(dict(chunks=logged_chunks, sampling=params), f)
        record["request_file"] = str(request_path)
        self.record(record | {"event": "request_started"})
        future = None
        try:
            for attempt in range(1, self.attempts + 1):
                try:
                    if self.session is None:
                        self.session = self._post("create_session", dict(tags=["gym-anything-rt-eval"],
                            user_metadata={"model": self.model, "purpose": "base-model evaluation"},
                            sdk_version="0.25.0"), deadline).json()["session_id"]
                    if self.sampler is None:
                        self.sampler = self._post("create_sampling_session", dict(session_id=self.session,
                            sampling_session_seq_id=0, base_model=self.model), deadline).json()["sampling_session_id"]
                    self._post("session_heartbeat", {"session_id": self.session}, deadline)
                    if future is None:
                        future = self._post("asample", dict(prompt=prompt, num_samples=1,
                            sampling_params=params, sampling_session_id=self.sampler, seq_id=self.seq,
                            conversation_id=self.sampler, type="sample"), deadline).json()["request_id"]
                        self.record(record | {"event": "request_accepted", "request_id": future,
                                              "sampling_session_id": self.sampler})
                    last_heartbeat = time.monotonic()
                    while True:
                        response = self._post("retrieve_future", {"request_id": future}, deadline)
                        if "protobuf" in response.headers.get("content-type", ""):
                            result = deserialize_sample_response(response.content)
                            sequence = result.sequences[0]
                            tokens = list(sequence.tokens)
                            logprobs = list(sequence.logprobs) if sequence.logprobs is not None else None
                            cached, stop = int(result.prompt_cache_hit_tokens), sequence.stop_reason
                            break
                        value = response.json()
                        if value.get("type") != "try_again":
                            raise RuntimeError("Tinker sampling failed: " + json.dumps(value)[:1500])
                        if time.monotonic() - last_heartbeat > 30:
                            self._post("session_heartbeat", {"session_id": self.session}, deadline)
                            last_heartbeat = time.monotonic()
                        time.sleep(min(0.25, max(0, deadline - time.monotonic())))
                    raw_text = self.tokenizer.decode(tokens, skip_special_tokens=False)
                    reasoning = reasoning_length(tokens, self.tokenizer.convert_tokens_to_ids("</think>"))
                    self.record(record | dict(event="request_completed", request_id=future,
                        sampling_session_id=self.sampler, attempts=attempt, wall_seconds=time.monotonic()-started,
                        output_tokens=len(tokens), reasoning_tokens=reasoning,
                        reasoning_count_method="emitted token IDs before </think>, excluding delimiter",
                        answer_tokens=len(tokens)-reasoning-(1 if reasoning < len(tokens) else 0),
                        cached_input_tokens=cached, stop_reason=stop, output_token_ids=tokens,
                        output_logprobs=logprobs, raw_text=raw_text,
                        reasoning_text=self.tokenizer.decode(tokens[:reasoning], skip_special_tokens=False)))
                    return "<think>\n" + raw_text.removesuffix(self.tokenizer.eos_token)
                except Exception as error:
                    self.record(record | dict(event="request_error", attempt=attempt, request_id=future,
                        error_type=type(error).__name__, error=str(error), retryable=retryable(error)))
                    if not retryable(error) or attempt == self.attempts or time.monotonic() >= deadline:
                        raise
                    time.sleep(min(attempt, max(0, deadline-time.monotonic())))
        finally:
            self.seq += 1


class TinkerRealTimeQwen35VLAgent(RealTimeQwen35VLAgent):
    """Change only Qwen35VL's model transport, usage recording, and retry ownership."""

    def init(self, task_description, display_resolution, save_path):
        super().init(task_description, display_resolution, save_path)
        self.tinker = TinkerSampling(model=self.model,
            tokenizer_path=self.agent_args["tokenizer_path"],
            base_url=os.environ["TINKER_BASE_URL"], api_key=os.environ["TINKER_API_KEY"],
            log_dir=Path(save_path) / "tinker", timeout=self.agent_args.get("tinker_timeout_seconds", 900),
            attempts=self.agent_args.get("tinker_attempts", 3))
        self.llm_call = self._sample

    def get_system_prompt(self):
        from gym_anything_rt.evaluate import VISIBLE_UI_ONLY_RULE
        return super().get_system_prompt() + "\n\n" + VISIBLE_UI_ONLY_RULE

    def _sample(self, messages, model, temperature, top_p, top_k, max_tokens):
        # The parent tries context variants on every exception. Do not let that
        # repeat exhausted provider calls or retry authentication/invalid requests.
        if getattr(self, "_failed_step", None) == self.step_idx:
            raise self._provider_error
        try:
            return self.tinker.sample(messages, step=self.step_idx, temperature=temperature,
                top_p=top_p, top_k=top_k, max_tokens=max_tokens, image_paths=self.b64_to_path)
        except ContextLengthError:
            # This request was never submitted. Keep the parent's smaller-history
            # fallback, without repeating a failed provider request.
            raise
        except Exception as error:
            self._failed_step, self._provider_error = self.step_idx, error
            raise
