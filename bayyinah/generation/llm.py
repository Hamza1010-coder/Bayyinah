"""LLM backends.

Two implementations, one interface:

``ExtractiveLLM``  -- no network, no key, deterministic. Selects verbatim
                      sentences from the retrieved context. It is the default
                      so that `git clone && python -m bayyinah.api.serve` works,
                      and it doubles as a retrieval-quality probe: if the
                      extractive baseline cannot answer, retrieval failed, not
                      generation.

``OpenAICompatLLM`` -- any OpenAI-compatible endpoint (OpenAI, vLLM, Ollama,
                      TGI, or a self-hosted ALLaM server). stdlib urllib only.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Protocol, Sequence

from ..text.normalize import tokenize
from .prompts import SYSTEM_AR, build_contract_prompt, build_user_prompt

SENTENCE = re.compile(r"(?<=[.؟!:؛])\s+|\n+")


class LLM(Protocol):
    name: str

    def generate(self, question: str, chunks: Sequence, *, problems: list[str] | None = None) -> dict: ...


class ExtractiveLLM:
    """Verbatim-sentence baseline. Cannot hallucinate a quote by construction."""

    name = "extractive-baseline"

    def __init__(self, max_sentences: int = 2, max_chunks: int = 2):
        self.max_sentences = max_sentences
        self.max_chunks = max_chunks

    def generate(self, question: str, chunks: Sequence, *, problems: list[str] | None = None) -> dict:
        q_terms = set(tokenize(question))
        scored: list[tuple[float, object, str]] = []

        # Rank sentences by how many *distinctive* query terms they contain.
        # Without the inverse-length weighting this baseline happily quotes a
        # generic article that merely repeats "العامل".
        for rank, chunk in enumerate(chunks[: self.max_chunks]):
            sentences = [s.strip() for s in SENTENCE.split(chunk.text_display) if len(s.strip()) > 25]
            for sent in sentences:
                s_terms = set(tokenize(sent))
                if not s_terms:
                    continue
                matched = q_terms & s_terms
                if not matched:
                    continue
                density = len(matched) / max(len(s_terms), 1)
                score = len(matched) * (1.0 + density) - 0.05 * rank
                scored.append((score, chunk, sent))

        if not scored:
            return {
                "answer": "لم أجد في المصادر المتاحة نصاً يغطي هذا السؤال.",
                "citations": [],
                "confidence": "low",
                "refusal": "no_evidence",
                "risk_flags": [],
            }

        scored.sort(key=lambda t: t[0], reverse=True)
        picked = scored[: self.max_sentences]

        # De-duplicate citations per article, keep the best sentence.
        seen: dict[tuple[str, str], str] = {}
        for _, chunk, sent in picked:
            key = (chunk.doc_id, str(chunk.article_no))
            if key not in seen:
                seen[key] = sent

        answer = " ".join(sent for _, _, sent in picked)
        citations = [
            {"doc_id": doc_id, "article_no": art, "quote": quote}
            for (doc_id, art), quote in seen.items()
        ]
        return {
            "answer": answer,
            "citations": citations,
            "confidence": "medium",
            "refusal": None,
            "risk_flags": [],
        }

    def contract_verdict(self, clause: str, chunks: Sequence) -> dict | None:
        """Rules cover the common violations; the baseline adds nothing."""
        return None


class OpenAICompatLLM:  # pragma: no cover - network path
    """OpenAI-compatible chat completions with JSON output."""

    def __init__(
        self,
        model: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout: int = 60,
    ):
        self.model = model or os.getenv("BAYYINAH_LLM_MODEL", "gpt-4o-mini")
        self.base_url = (base_url or os.getenv("BAYYINAH_LLM_BASE_URL", "https://api.openai.com/v1")).rstrip("/")
        self.api_key = api_key or os.getenv("BAYYINAH_LLM_API_KEY", "")
        self.timeout = timeout
        self.name = f"openai-compat:{self.model}"

    def generate(self, question: str, chunks: Sequence, *, problems: list[str] | None = None) -> dict:
        payload = {
            "model": self.model,
            "temperature": 0.0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": SYSTEM_AR},
                {"role": "user", "content": build_user_prompt(question, list(chunks), problems=problems)},
            ],
        }
        return self._post(payload)

    def contract_verdict(self, clause: str, chunks: Sequence) -> dict | None:
        if not chunks:
            return None
        payload = {
            "model": self.model,
            "temperature": 0.0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": SYSTEM_AR},
                {"role": "user", "content": build_contract_prompt(clause, list(chunks))},
            ],
        }
        try:
            result = self._post(payload)
        except (RuntimeError, ValueError):
            return None
        if not isinstance(result, dict) or "verdict" not in result:
            return None
        return result

    def _post(self, payload: dict) -> dict:
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise RuntimeError(f"LLM call failed: {exc}") from exc

        text = body["choices"][0]["message"]["content"]
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # One salvage attempt: models like to wrap JSON in prose.
            match = re.search(r"\{.*\}", text, re.S)
            if match:
                return json.loads(match.group(0))
            raise ValueError(f"LLM returned non-JSON: {text[:200]}")


def get_default_llm() -> LLM:
    if os.getenv("BAYYINAH_LLM_BASE_URL") or os.getenv("BAYYINAH_LLM_API_KEY"):
        return OpenAICompatLLM()
    return ExtractiveLLM()
