"""
AI Chat & Desktop Memory Synthesis for mem-vision-mcp.
Retrieves relevant screen context, active URLs, and OCR text, then synthesizes answers via LLM APIs
(supports Meta Model API / Llama 3, OpenAI, Ollama, Groq, and local endpoints).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
import httpx

from memvision.config import AppConfig
from memvision.storage import CaptureRecord, MemoryStorage

logger = logging.getLogger(__name__)


@dataclass
class ChatResponse:
    answer: str
    citations: List[CaptureRecord]
    model_used: str
    tokens_used: Optional[int] = None


class AIChatEngine:
    """
    RAG-powered conversational engine over local screen memory.
    Connects user queries to desktop captures and synthesizes answers using LLMs.
    """

    def __init__(self, config: Optional[AppConfig] = None, storage: Optional[MemoryStorage] = None):
        self.config = config or AppConfig()
        self.storage = storage or MemoryStorage(
            self.config.storage.database_path,
            self.config.storage.enable_fts,
        )

    def get_api_credentials(self) -> Dict[str, str]:
        """
        Intelligently resolves API Key, Base URL, and Model from environment.
        Auto-configures the correct endpoint based on whichever API key is present:
        Meta, OpenAI, Groq, OpenRouter, DeepSeek, Gemini, or Ollama.
        """
        api_cfg = self.config.ai

        # 1. Detect provider from environment keys
        api_key = ""
        base_url = ""
        model = ""
        provider_detected = "meta"

        if os.environ.get("OPENAI_API_KEY"):
            api_key = os.environ["OPENAI_API_KEY"]
            base_url = "https://api.openai.com/v1"
            model = "gpt-4o-mini"
            provider_detected = "openai"
        elif os.environ.get("GROQ_API_KEY"):
            api_key = os.environ["GROQ_API_KEY"]
            base_url = "https://api.groq.com/openai/v1"
            model = "llama-3.3-70b-versatile"
            provider_detected = "groq"
        elif os.environ.get("OPENROUTER_API_KEY"):
            api_key = os.environ["OPENROUTER_API_KEY"]
            base_url = "https://openrouter.ai/api/v1"
            model = "meta-llama/llama-3.3-70b-instruct"
            provider_detected = "openrouter"
        elif os.environ.get("DEEPSEEK_API_KEY"):
            api_key = os.environ["DEEPSEEK_API_KEY"]
            base_url = "https://api.deepseek.com/v1"
            model = "deepseek-chat"
            provider_detected = "deepseek"
        elif os.environ.get("GEMINI_API_KEY"):
            api_key = os.environ["GEMINI_API_KEY"]
            base_url = "https://generativelanguage.googleapis.com/v1beta/openai"
            model = "gemini-2.0-flash"
            provider_detected = "gemini"
        elif os.environ.get("META_API_KEY") or os.environ.get(api_cfg.api_key_env):
            api_key = os.environ.get("META_API_KEY") or os.environ.get(api_cfg.api_key_env, "")
            base_url = api_cfg.base_url
            model = api_cfg.model
            provider_detected = "meta"
        elif os.environ.get("LLM_API_KEY"):
            api_key = os.environ["LLM_API_KEY"]
            base_url = api_cfg.base_url
            model = api_cfg.model
            provider_detected = "custom"
        else:
            # Default / fallback settings
            base_url = api_cfg.base_url
            model = api_cfg.model

        # Overrides from explicit environment variables
        if os.environ.get("LLM_BASE_URL"):
            base_url = os.environ["LLM_BASE_URL"]
        if os.environ.get("LLM_MODEL"):
            model = os.environ["LLM_MODEL"]

        return {
            "api_key": api_key.strip(),
            "base_url": base_url.rstrip("/"),
            "model": model,
            "provider": provider_detected,
        }

    def retrieve_context(self, query: str, limit: int = 6) -> List[CaptureRecord]:
        """
        Retrieves the most relevant captures using temporal or FTS5 keyword matching.
        """
        import re
        clean_q = query.strip().lower()
        temporal_triggers = {"today", "yesterday", "recently", "just now", "recent", "latest", "what did i do"}

        # If general temporal inquiry, fetch recent records
        if any(trigger in clean_q for trigger in temporal_triggers) and len(clean_q.split()) <= 6:
            records = self.storage.get_recent(limit=limit * 2)
        else:
            # 1. Try full phrase / query search
            records = self.storage.search(query, limit=limit * 2)

            # 2. If no direct match, extract significant keywords and search
            if not records:
                stop_words = {
                    "what", "when", "where", "which", "about", "show", "tell",
                    "that", "this", "have", "with", "from", "were", "been",
                    "does", "could", "would", "should", "some", "your", "mine",
                    "i", "me", "my", "was", "the", "and", "or", "in", "on", "at"
                }
                stripped = re.sub(r"[^\w\s]", " ", clean_q)
                keywords = [w for w in stripped.split() if len(w) > 2 and w not in stop_words]

                for kw in keywords:
                    kw_records = self.storage.search(kw, limit=limit)
                    if kw_records:
                        records.extend(kw_records)
                    if len(records) >= limit * 2:
                        break

        # Deduplicate consecutive frames of the same app and identical text
        deduped: List[CaptureRecord] = []
        seen_hashes = set()
        for r in records:
            if r.phash in seen_hashes:
                continue
            seen_hashes.add(r.phash)
            deduped.append(r)
            if len(deduped) >= limit:
                break

        return deduped

    def _build_system_prompt(self, context_records: List[CaptureRecord]) -> str:
        """Constructs an intelligent system prompt embedding the retrieved screen memory."""
        context_blocks = []
        for i, r in enumerate(context_records, 1):
            url_line = f"URL: {r.url}" if r.url else "URL: None"
            # Clean OCR text snippet (limit to 500 chars per record to keep prompt compact)
            ocr_snippet = r.ocr_text.strip().replace("\n", " ")[:500] if r.ocr_text else "[No text detected]"
            block = (
                f"--- [MEMORY REFERENCE #{i}] ---\n"
                f"Capture ID: {r.id}\n"
                f"Timestamp (UTC): {r.timestamp}\n"
                f"Application: {r.app_name}\n"
                f"Window Title: {r.window_title}\n"
                f"{url_line}\n"
                f"Screenshot Path: {r.screenshot_path or 'None'}\n"
                f"On-Screen OCR Text:\n\"{ocr_snippet}\"\n"
            )
            context_blocks.append(block)

        memories_text = "\n".join(context_blocks) if context_blocks else "No relevant memory records found."

        return (
            "You are MemVision AI, an intelligent personal desktop memory assistant.\n"
            "You have access to historical screen captures, active applications, browser URLs, and on-screen text.\n\n"
            "Here is the verified desktop context retrieved from the user's screen:\n\n"
            f"{memories_text}\n"
            "======================================================================\n"
            "Instructions:\n"
            "1. Answer the user's question directly and concisely using ONLY the provided memory references.\n"
            "2. Whenever mentioning a past event, ALWAYS cite the reference details (e.g. 'According to Memory #1 at 22:45 UTC in Brave [dev.meta.ai]...').\n"
            "3. If a URL is available in the reference, include the clickable link in markdown format [Title](URL).\n"
            "4. If the provided memory does not contain the answer, politely state what was found and suggest alternative keywords."
        )

    def ask(self, question: str, max_context: Optional[int] = None) -> ChatResponse:
        """
        Processes a user question: retrieves memory, calls LLM API, and returns cited answer.
        """
        limit = max_context or self.config.ai.max_context_items
        citations = self.retrieve_context(question, limit=limit)
        creds = self.get_api_credentials()
        api_key = creds["api_key"]
        base_url = creds["base_url"]
        model = creds["model"]

        system_prompt = self._build_system_prompt(citations)

        # If no API key is provided, produce a local synthesis summary without failing
        if not api_key:
            logger.info("No API key detected in environment. Generating local summary response.")
            if not citations:
                answer = (
                    "I searched your desktop memory, but found no matching records for your query.\n\n"
                    "💡 *Tip: Try searching for a specific application name (e.g. 'Brave', 'Antigravity') or a topic.*"
                )
            else:
                summary_lines = [
                    f"Found **{len(citations)}** relevant screen memories. *(Set `$env:META_API_KEY` or `$env:OPENAI_API_KEY` to enable AI conversational answers)*:\n"
                ]
                for i, r in enumerate(citations, 1):
                    url_str = f" - [{r.url}]({r.url})" if r.url else ""
                    summary_lines.append(
                        f"**{i}. [{r.app_name}]** {r.window_title}{url_str}\n"
                        f"   • *Time:* {r.timestamp[:19].replace('T', ' ')}\n"
                        f"   • *Snippet:* {r.ocr_text.strip().replace(chr(10), ' ')[:140]}...\n"
                    )
                answer = "\n".join(summary_lines)

            return ChatResponse(
                answer=answer,
                citations=citations,
                model_used="local-search-fallback (no API key set)",
            )

        # Call OpenAI/Meta Model API compatible endpoint
        endpoint = f"{base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": question},
            ],
            "temperature": self.config.ai.temperature,
            "max_tokens": self.config.ai.max_tokens,
        }

        try:
            with httpx.Client(timeout=45.0) as client:
                resp = client.post(endpoint, headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()

            answer = data["choices"][0]["message"]["content"]
            tokens = data.get("usage", {}).get("total_tokens")
            return ChatResponse(
                answer=answer,
                citations=citations,
                model_used=model,
                tokens_used=tokens,
            )

        except httpx.HTTPStatusError as e:
            logger.error("LLM API HTTP Error: %s - %s", e.response.status_code, e.response.text)
            return ChatResponse(
                answer=f"⚠️ LLM API Error ({e.response.status_code}): {e.response.text}",
                citations=citations,
                model_used=model,
            )
        except Exception as err:
            logger.error("Failed to query LLM API: %s", err)
            return ChatResponse(
                answer=f"⚠️ Failed to communicate with LLM API: {err}",
                citations=citations,
                model_used=model,
            )
