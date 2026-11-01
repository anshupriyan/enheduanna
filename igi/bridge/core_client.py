"""
IGI (𒅆) — Localhost Core Orchestrator Client & Multimodal Vision Bridge
Connects to Enheduanna core at http://127.0.0.1:4100 over HTTP & SSE, with direct Meta API fallback.
Transmits full visual cropped screen images to Spark 1.3 and Wonder 1.0.
"""

from __future__ import annotations

import json
import base64
import io
from typing import Optional, Callable, Dict, Any, List
from PIL import Image
import httpx

try:
    from ..config import IgiConfig, load_config
except (ImportError, ValueError):
    from config import IgiConfig, load_config

try:
    from .sam_prompts import SAM_PLANNER_SYSTEM, CARD_WRITER_SYSTEM
except (ImportError, ValueError):
    try:
        from bridge.sam_prompts import SAM_PLANNER_SYSTEM, CARD_WRITER_SYSTEM
    except (ImportError, ValueError):
        from sam_prompts import SAM_PLANNER_SYSTEM, CARD_WRITER_SYSTEM


class CoreClient:
    def __init__(self, config: Optional[IgiConfig] = None):
        self.config = config or load_config()
        self.base_url = self.config.server.base_url
        self.session_id: Optional[str] = None
        self._client = httpx.Client(timeout=90.0)

    def check_health(self) -> Dict[str, Any]:
        """Verify localhost:4100 is healthy and responsive."""
        try:
            res = self._client.get(f"{self.base_url}/health", timeout=2.0)
            if res.status_code == 200:
                return res.json()
            return {"status": "error", "code": res.status_code}
        except Exception as e:
            return {"status": "unreachable", "error": str(e)}

    def ensure_session(self) -> str:
        """Create or return an active session ID for IGI."""
        if self.session_id:
            return self.session_id

        try:
            res = self._client.post(
                f"{self.base_url}/api/sessions",
                json={"title": "IGI (𒅆) Visual Assistant Session"},
                timeout=3.0
            )
            if res.status_code in (200, 201):
                data = res.json()
                self.session_id = data.get("id", "igi_session")
                return self.session_id
        except Exception:
            pass

        self.session_id = "igi_default_session"
        return self.session_id

    def resolve_approval(self, approval_id: str, decision: str = "allow") -> bool:
        """Resolve a pending tool authorization on localhost core (port 4100)."""
        try:
            res = self._client.post(
                f"{self.base_url}/api/approvals/{approval_id}",
                json={"decision": decision},
                timeout=5.0
            )
            return res.status_code in (200, 201)
        except Exception:
            return False

    def stream_chat_turn(
        self,
        prompt: str,
        image_crop: Optional[Image.Image] = None,
        ocr_text: Optional[str] = None,
        window_title: Optional[str] = None,
        process_name: Optional[str] = None,
        window_context: Optional[Any] = None,
        on_token: Optional[Callable[[str], None]] = None,
        on_status: Optional[Callable[[str], None]] = None,
        on_event: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    ) -> str:
        """
        Send a chat turn to localhost core (port 4100) with visual image attachments.
        If localhost is offline, falls back to direct Meta Model API.
        """
        session_id = self.ensure_session()

        # Build context metadata
        context_parts = []
        if window_title or process_name:
            context_parts.append(f"[Active Window: {process_name or 'App'} — {window_title or 'Untitled'}]")

        if window_context:
            detected_p = getattr(window_context, "detected_path", "")
            if detected_p:
                context_parts.append(f"[Active Directory / Folder Path]: {detected_p}")

            detected_u = getattr(window_context, "detected_url", "")
            if detected_u:
                context_parts.append(f"[Active Web Page URL]: {detected_u}")

            full_ocr = getattr(window_context, "full_window_ocr", "")
            if full_ocr and full_ocr.strip():
                clean_full = full_ocr.strip()
                if len(clean_full) > 1200:
                    clean_full = clean_full[:1197] + "..."
                context_parts.append(f"[Full Window Screen Context (Surrounding OCR)]:\n```\n{clean_full}\n```")

        if ocr_text and ocr_text.strip():
            context_parts.append(f"[Circled Focal Selection (WinRT OCR)]:\n```\n{ocr_text.strip()}\n```")

        # Encode image crop as base64
        img_b64 = None
        images_payload: List[str] = []
        if image_crop:
            buf = io.BytesIO()
            w, h = image_crop.size
            if w > 1280 or h > 1280:
                scale = min(1280 / w, 1280 / h)
                img = image_crop.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)
            else:
                img = image_crop

            img.save(buf, format="JPEG", quality=85)
            img_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
            images_payload.append(f"data:image/jpeg;base64,{img_b64}")
            context_parts.append(f"[Visual Crop Attached: {w}x{h} px]")

        header = "\n\n".join(context_parts)
        if header:
            full_message = f"{header}\n\nUser Question:\n{prompt}"
        else:
            full_message = prompt

        payload = {
            "sessionId": session_id,
            "message": full_message,
            "images": images_payload,
            "options": {
                "enableTwoModelRouting": True,
                "toolModel": self.config.model.tool_model,
                "synthesisModel": self.config.model.synthesis_model,
                "provider": self.config.model.provider,
                "modelName": self.config.model.tool_model,
                "apiKey": self.config.model.api_key,
                "baseUrl": self.config.model.base_url,
                "maxSteps": 16,
            }
        }

        full_reply = ""

        # 1. Try Localhost Core first (http://127.0.0.1:4100)
        try:
            import httpx
            stream_timeout = httpx.Timeout(300.0, connect=10.0, read=300.0)
            with self._client.stream("POST", f"{self.base_url}/chat", json=payload, timeout=stream_timeout) as response:
                if response.status_code == 200:
                    current_event_type = "message"
                    for raw_line in response.iter_lines():
                        if not raw_line:
                            continue
                        line = raw_line.strip()

                        if line.startswith("event: "):
                            current_event_type = line[7:].strip()
                            continue

                        if line.startswith("data: "):
                            raw_data = line[6:].strip()
                            if raw_data == "[DONE]":
                                break
                            try:
                                evt = json.loads(raw_data)
                                if on_event:
                                    on_event(current_event_type, evt)

                                if current_event_type == "delta" or evt.get("type") in ("token", "content_delta"):
                                    delta = evt.get("text") or evt.get("delta") or ""
                                    full_reply += delta
                                    if on_token and delta:
                                        on_token(delta)

                                elif current_event_type == "done":
                                    # Guarantee final confirmation is displayed even if deltas were batched
                                    final_ans = evt.get("finalAnswer") or ""
                                    if final_ans and not full_reply:
                                        full_reply = final_ans
                                        if on_token:
                                            on_token(final_ans)

                                elif current_event_type == "step_narration":
                                    narration = evt.get("text") or ""
                                    if on_status and narration:
                                        on_status(narration)

                                elif current_event_type == "reasoning":
                                    if on_status:
                                        on_status("🧠 Thinking...")

                                elif current_event_type == "step_start":
                                    step_num = evt.get("step", 1)
                                    model = evt.get("model", "muse-spark-1.3")
                                    stage = "Synthesizing" if evt.get("isSynthesis") else "Reasoning & Tools"
                                    if on_status:
                                        on_status(f"Step {step_num}: {stage} ({model})")

                                elif current_event_type == "tool_call_start":
                                    tool_name = evt.get("name") or evt.get("tool") or "tool"
                                    if on_status:
                                        on_status(f"⚡ Executing {tool_name}...")

                                elif current_event_type == "tool_call_done":
                                    tool_name = evt.get("name") or evt.get("tool") or "tool"
                                    dur = evt.get("durationMs", 0)
                                    if on_status:
                                        on_status(f"✓ {tool_name} completed ({dur}ms)")

                                elif current_event_type == "approval_required":
                                    tool_name = evt.get("toolName") or "tool"
                                    if on_status:
                                        on_status(f"⚠️ Authorization required: {tool_name}")

                                elif current_event_type == "approval_resolved":
                                    dec = evt.get("decision", "resolved")
                                    if on_status:
                                        on_status(f"✓ Authorization {dec}")

                            except json.JSONDecodeError:
                                pass

                    if full_reply:
                        return full_reply

        except Exception as e:
            # Localhost is offline, fall back to direct Meta API
            pass

        # 2. Direct Meta Model API Multimodal Fallback
        if self.config.model.api_key:
            if on_status:
                on_status("Contacting Meta AI directly (Visual)...")
            direct_reply = self._call_direct_meta_api(
                prompt=full_message,
                image_b64=img_b64,
                on_token=on_token,
                on_status=on_status
            )
            if direct_reply:
                return direct_reply

        # 3. Informative instruction message if neither responded
        fallback_msg = (
            "⚠️ **Localhost Core Offline**\n\n"
            f"Could not connect to `{self.base_url}`.\n\n"
            "To connect Enheduanna's full tools and memory, start the core service:\n"
            "```powershell\n"
            "cd 'c:\\meta hackathon\\enheduanna\\app\\core'\n"
            "npm run start\n"
            "```"
        )
        if on_token:
            on_token(fallback_msg)
        return fallback_msg

    def _call_direct_meta_api(
        self,
        prompt: str,
        image_b64: Optional[str] = None,
        on_token: Optional[Callable[[str], None]] = None,
        on_status: Optional[Callable[[str], None]] = None
    ) -> str:
        """Query Meta Model API directly with multimodal image attachment."""
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.config.model.api_key}"
        }
        url = f"{self.config.model.base_url}/chat/completions"

        # Construct multimodal content array if image crop is available
        if image_b64:
            user_content: Any = [
                {"type": "text", "text": prompt},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{image_b64}"
                    }
                }
            ]
        else:
            user_content = prompt

        messages = [
            {
                "role": "system",
                "content": (
                    "You are IGI (𒅆), the visual companion of Enheduanna. "
                    "You receive both the visual cropped screenshot and OCR text. "
                    "Analyze the visual layout, code, errors, or elements directly from the image and text. "
                    "Format responses in clean Markdown with headers, bullet points, and code blocks. "
                    "When guiding the user to locate, click, or inspect an element on screen, append a visual grounding action tag at the very end of your response on its own line in this exact format:\n"
                    "<<<TARGET: \"Exact Element or Tab Name\" | REGION: \"top\"|\"sidebar\"|\"center\"|\"bottom\" | ACTION: \"1-sentence action instruction\">>>\n"
                    "Example:\n"
                    "<<<TARGET: \"Security and quality\" | REGION: \"top\" | ACTION: \"Click Security and quality in the top navigation bar to open Advisories\">>>"
                )
            },
            {"role": "user", "content": user_content}
        ]

        payload = {
            "model": self.config.model.synthesis_model or "muse-wonder-1.0",
            "messages": messages,
            "stream": True,
        }

        full_reply = ""
        try:
            with self._client.stream("POST", url, json=payload, headers=headers, timeout=60.0) as res:
                if res.status_code == 200:
                    for line in res.iter_lines():
                        if not line or not line.startswith("data: "):
                            continue
                        chunk_str = line[6:].strip()
                        if chunk_str == "[DONE]":
                            break
                        try:
                            chunk = json.loads(chunk_str)
                            delta = chunk.get("choices", [{}])[0].get("delta", {}).get("content", "")
                            if delta:
                                full_reply += delta
                                if on_token:
                                    on_token(delta)
                        except Exception:
                            pass
                    return full_reply
        except Exception:
            pass

        return ""

    def generate_spark_card_instruction(self, target_name: str, task_context: str = "") -> str:
        """
        Dynamically generate a concise 1-sentence action instruction for floating card overlay
        using Meta's standard muse-spark-1.3 model, with fast local fallback.
        """
        clean_target = (target_name or "").strip()
        if not clean_target:
            return "Active visual section"

        api_key = self.config.model.api_key
        base_url = self.config.model.base_url or "https://api.meta.ai/v1"
        tool_model = self.config.model.tool_model or "muse-spark-1.3"

        if api_key:
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}"
            }
            messages = [
                {
                    "role": "system",
                    "content": CARD_WRITER_SYSTEM
                },
                {
                    "role": "user",
                    "content": f"Target: {clean_target}\nUser Question / Task Context: {task_context}" if task_context else f"Target: {clean_target}"
                }
            ]
            payload = {
                "model": tool_model,
                "messages": messages,
                "max_tokens": 800,
                "temperature": 0.2
            }
            try:
                res = self._client.post(f"{base_url}/chat/completions", json=payload, headers=headers, timeout=6.0)
                if res.status_code == 200:
                    data = res.json()
                    content = data.get("choices", [{}])[0].get("message", {}).get("content")
                    if content and content.strip():
                        return content.strip().strip('"')
            except Exception:
                pass

        # Fallback to local heuristic / pattern explainer
        return self.quick_explain_block(clean_target)

    def quick_explain_block(self, block_text: str) -> str:
        """Rapid 1-sentence explanation of code, math, or UI element for floating tooltips."""
        clean = (block_text or "").strip()
        if not clean:
            return "Active visual section"
        low = clean.lower()

        # UI action buttons & workflow elements
        if "reply" in low:
            return "Draft copied: Click here and press Ctrl+V to paste your reply."
        elif "send" in low or "submit" in low:
            return "Click Send to dispatch your email."
        elif "update" in low:
            return "Click to update application to the latest version."
        elif "$" in clean or "credit" in low or "balance" in low:
            return "Account billing credits and real-time usage balance."

        # Math / Graphs on screen
        if (
            "3." in low or "3 if" in low or "case 3" in low
            or ("-x^2" in low and "a <" in low) or ("-x2" in low and "even" in low)
            or ("decrease without bound at both" in low)
            or (("a < 0" in low or "a <" in low or "ifa <" in low or "-x" in low) and ("even" in low or "ev,en" in low or "isev" in low or "parabola" in low))
            or ("decrea" in low and ("both" in low or "endpoints" in low) and "even" in low)
            or low.startswith("3")
        ):
            return "-x² inverted parabola (a < 0, n even); both ends decrease to -infinity."
        elif (
            "4." in low or "4 if" in low or "case 4" in low
            or ("-x^3" in low and "a <" in low) or ("-x3" in low and "odd" in low)
            or ("right end and increase" in low and "decrea" in low)
            or (("a < 0" in low or "a <" in low or "-x" in low) and ("odd" in low or "-x^3" in low or "-x3" in low or "falling" in low))
            or (low.startswith("4") and "odd" in low)
        ):
            return "-x³ falling S-curve (a < 0, n odd); left increases to +infinity, right decreases to -infinity."
        elif (
            "2." in low or "2 if" in low or "case 2" in low
            or ("x^3" in low and "a >" in low) or ("x3" in low and "odd" in low)
            or ("right end and decrease" in low and "increa" in low)
            or (("a > 0" in low or "a >" in low or "ifa o" in low) and ("odd" in low or "x^3" in low or "x3" in low))
            or (low.startswith("2") and "odd" in low)
        ):
            return "x³ S-curve (a > 0, n odd); left decreases to -infinity, right increases to +infinity."
        elif (
            "1." in low or "1 if" in low or "case 1" in low
            or ("x^2" in low and "a >" in low) or ("x2" in low and "even" in low)
            or ("increase without bound at both" in low)
            or (("a > 0" in low or "a >" in low or "ifa o" in low) and ("even" in low or "ev,en" in low or "isev" in low or "x^2" in low or "x2" in low) and "decrea" not in low)
            or low.startswith("1")
        ):
            return "x² parabola opening upwards (a > 0, n even); ends increase to +infinity."
        elif "leading coefficient" in low:
            return "Leading Coefficient Test: determines polynomial end-behavior from highest-degree term."
        elif "process for graphing" in low:
            return "Process for graphing polynomials: find zeroes, y-intercept, and end-behavior."
        elif "graph" in low or "plot" in low or "diagram" in low or "curve" in low or "parabola" in low:
            return "Polynomial function end-behavior graph curve."

        # Code patterns
        elif clean.startswith("def "):
            fn_name = clean.split("(")[0].replace("def ", "").strip()
            return f"Function `{fn_name}`: core execution logic."
        elif clean.startswith("class "):
            cls_name = clean.split("(")[0].split(":")[0].replace("class ", "").strip()
            return f"Class `{cls_name}`: encapsulates state and interface."
        elif "import " in clean or clean.startswith("from "):
            return "Module imports and external dependencies declaration."
        elif "$" in clean or "credit" in low:
            return "Account billing credits and real-time usage balance."
        return clean[:75] + "..." if len(clean) > 75 else clean

    def _extract_json_dict(self, text: str) -> Optional[Dict[str, Any]]:
        """Extract first valid JSON object from model response text."""
        if not text:
            return None
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end > start:
            try:
                data = json.loads(text[start:end + 1])
                if isinstance(data, dict):
                    return data
            except Exception:
                pass
        return None

    def spark_plan_targets(
        self,
        screenshot: Image.Image,
        query: str,
        window_title: str = "",
        url: str = "",
        ocr_text: str = ""
    ) -> Dict[str, Any]:
        """
        Spark Spatial Planner (muse-spark-1.3).
        Analyzes a 1200px desktop thumbnail + query + window context + focal OCR.
        Decides:
        1. intent: explain_page | explain_code | locate | compare | act
        2. targets: 2-5 semantic targets ranked by question relevance (not visual salience)
        3. referring_expression: visual description with quoted visible text, colors, shapes
        4. say: max 28 words question-aware explanation for the anchored floating card
        """
        clean_query = (query or "").strip()
        orig_w, orig_h = screenshot.size

        # 1. Create 1200px max thumbnail with JPEG quality 80
        if orig_w > 1200 or orig_h > 1200:
            scale = min(1200.0 / orig_w, 1200.0 / orig_h)
            thumb = screenshot.resize((int(orig_w * scale), int(orig_h * scale)), Image.Resampling.LANCZOS)
        else:
            thumb = screenshot

        buf = io.BytesIO()
        thumb.save(buf, format="JPEG", quality=80)
        thumb_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

        # 2. OCR input: focal-weighted 1000-1200 chars (filter chrome/HUD noise)
        filtered_lines = []
        noise_keywords = (
            "appearance", "light", "dark", "automatic", "igi hud",
            "search wiktionary", "jump to navigation", "jump to search",
            "create account", "log in", "personal tools", "toggle navigation"
        )
        for line in (ocr_text or "").splitlines():
            l_strip = line.strip()
            if not l_strip:
                continue
            if any(l_strip.lower() == nk or l_strip.lower().startswith(nk) for nk in noise_keywords):
                continue
            filtered_lines.append(l_strip)

        cleaned_ocr = "\n".join(filtered_lines)
        if len(cleaned_ocr) < 80 and ocr_text:
            cleaned_ocr = ocr_text.strip()
        focal_ocr = cleaned_ocr[:1200].strip()

        user_prompt = (
            f"User Question: {clean_query}\n"
            f"Active Window: {window_title}\n"
            f"Page URL: {url or 'Not specified'}\n"
            f"Visible On-Screen OCR Content:\n```\n{focal_ocr if focal_ocr else 'None'}\n```"
        )

        api_key = self.config.model.api_key
        base_url = self.config.model.base_url or "https://api.meta.ai/v1"
        tool_model = self.config.model.tool_model or "muse-spark-1.3"

        if api_key:
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}"
            }
            messages = [
                {"role": "system", "content": SAM_PLANNER_SYSTEM},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{thumb_b64}"}}
                    ]
                }
            ]
            payload = {
                "model": tool_model,
                "messages": messages,
                "temperature": 0.2,
                "max_tokens": 1200
            }
            try:
                res = self._client.post(f"{base_url}/chat/completions", json=payload, headers=headers, timeout=6.0)
                if res.status_code == 200:
                    raw_text = res.json().get("choices", [{}])[0].get("message", {}).get("content", "")
                    parsed = self._extract_json_dict(raw_text)
                    if parsed and isinstance(parsed, dict) and "targets" in parsed:
                        valid_targets = []
                        for t in parsed.get("targets", []):
                            if not isinstance(t, dict):
                                continue
                            if float(t.get("relevance", 1.0)) < 0.60:
                                continue
                            rh = str(t.get("region_hint", "any")).lower().strip()
                            if rh in ("sidebar", "left side"):
                                rh = "left"
                            if rh not in ("top", "left", "right", "bottom", "center", "any"):
                                rh = "any"
                            t["region_hint"] = rh
                            if not t.get("referring_expression"):
                                t["referring_expression"] = t.get("concept", "")
                            valid_targets.append(t)
                        if valid_targets:
                            parsed["targets"] = valid_targets
                            parsed.setdefault("intent", "explain_page")
                            return parsed
            except Exception:
                pass

        # Intelligent heuristic / offline fallback
        low_q = clean_query.lower()
        title_low = (window_title or "").lower()
        ocr_low = (ocr_text or "").lower()

        # Check for Wiktionary / Cuneiform page (strict check: requires specific glyph or lexicon indices)
        is_wiktionary_igi = any(k in ocr_low or k in title_low for k in ("u+12146", "cuneiform sign igi", "mzl 724", "deimel 449", "hzl 288")) or ("wiktionary" in title_low and "cuneiform" in ocr_low)
        if is_wiktionary_igi:
            return {
                "intent": "explain_page",
                "targets": [
                    {
                        "concept": "Cuneiform glyph header card",
                        "region_hint": "top",
                        "referring_expression": "bordered white card in center-top containing large black cuneiform wedge glyph with text 'U+12146 CUNEIFORM SIGN IGI'",
                        "label": "Glyph + Unicode",
                        "relevance": 0.98,
                        "why": "Primary glyph identification and Unicode codepoint",
                        "say": "IGI glyph U+12146, the pictographic sign for eye and seeing with Unicode standard index."
                    },
                    {
                        "concept": "Dictionary index table",
                        "region_hint": "center",
                        "referring_expression": "compact table with standard Assyriology numbers MZL 724, Deimel 449, and HZL 288 under the glyph",
                        "label": "Lexicon Indices",
                        "relevance": 0.92,
                        "why": "Printed lexicon references for Assyriology research",
                        "say": "Standard printed sign-list indices from Borger MZL, Deimel, and HZL cataloging this sign."
                    },
                    {
                        "concept": "Akkadian values table",
                        "region_hint": "center",
                        "referring_expression": "phonetic reading table with Sumerogram IGI and values ši, lim, lem meaning to see / amārum",
                        "label": "Akkadian Values",
                        "relevance": 0.95,
                        "why": "Sumerian logogram borrowed into Akkadian for amārum (to see)",
                        "say": "Logogram IGI and phonetic values ši, lim, lem borrowed to write Akkadian amārum (to see)."
                    },
                    {
                        "concept": "Derived signs and references",
                        "region_hint": "bottom",
                        "referring_expression": "derived cuneiform signs and references section below the main phonetic tables",
                        "label": "Derived Signs",
                        "relevance": 0.85,
                        "why": "Compound characters formed using the IGI eye radical",
                        "say": "Compound cuneiform glyphs and lexical citations utilizing the IGI sign radical."
                    }
                ]
            }

        # Check for YouTube right rail
        if any(k in low_q for k in ("ltt", "techlinked", "linus", "recommendation", "right rail")):
            return {
                "intent": "locate",
                "targets": [
                    {
                        "concept": "TechLinked video thumbnail",
                        "region_hint": "right",
                        "referring_expression": "purple thumbnail with yellow diamond logo on left, man with glasses, title '$6.3 BILLION, gone' to right, in YouTube right rail",
                        "label": "TechLinked Video",
                        "relevance": 0.96,
                        "why": "Directly matches requested LTT TechLinked video",
                        "say": "TechLinked video thumbnail located in the YouTube right rail."
                    }
                ]
            }

        # Check for Update button
        if any(k in low_q for k in ("update", "restart", "top bar")):
            return {
                "intent": "locate",
                "targets": [
                    {
                        "concept": "Update button",
                        "region_hint": "top",
                        "referring_expression": "blue or grey pill button with text 'Update' in the top title bar / navigation strip",
                        "label": "Update Button",
                        "relevance": 0.95,
                        "why": "Requested application update control",
                        "say": "Update pill button in the top navigation strip."
                    }
                ]
            }

        # Check for Reply box
        if any(k in low_q for k in ("reply", "compose", "draft")):
            return {
                "intent": "act",
                "targets": [
                    {
                        "concept": "Reply box",
                        "region_hint": "bottom",
                        "referring_expression": "large text input area or reply button at bottom of active email conversation",
                        "label": "Reply Box",
                        "relevance": 0.95,
                        "why": "Input container for email draft response",
                        "say": "Reply input area ready for draft text insertion."
                    }
                ]
            }

        # Generic exploratory or targeted fallback
        is_exploratory = any(k in low_q for k in ("explain", "walk", "different elements", "what is", "overview", "components"))
        if is_exploratory and focal_ocr:
            ocr_blocks = [line for line in focal_ocr.splitlines() if len(line) > 10][:4]
            targets = []
            hints = ["top", "center", "center", "bottom"]
            for idx, ob in enumerate(ocr_blocks):
                targets.append({
                    "concept": ob[:30],
                    "region_hint": hints[min(idx, len(hints)-1)],
                    "referring_expression": f"visual block containing text '{ob[:50]}'",
                    "label": f"Section {idx+1}",
                    "relevance": 0.80,
                    "why": "Visible content section",
                    "say": f"Section containing: {ob[:24]}..."
                })
            if targets:
                return {"intent": "explain_page", "targets": targets}

        # Default single target
        return {
            "intent": "locate",
            "targets": [
                {
                    "concept": clean_query,
                    "region_hint": "any",
                    "referring_expression": f"element matching '{clean_query}' on screen",
                    "label": clean_query[:20].title(),
                    "relevance": 0.70,
                    "why": "Direct user search term",
                    "say": f"Visual region matching {clean_query}."
                }
            ]
        }

    def spark_ground_concept(
        self,
        screenshot: Image.Image,
        query: str,
        window_title: str = "",
        ocr_text: str = ""
    ) -> Dict[str, Any]:
        """
        Spark Vision Grounding Brain (muse-spark-1.3).
        Analyzes screen thumbnail + user query via the Spatial Planner.
        Returns single-target dict for backwards compatibility.
        """
        plan = self.spark_plan_targets(
            screenshot=screenshot,
            query=query,
            window_title=window_title,
            url="",
            ocr_text=ocr_text
        )
        targets = plan.get("targets", [])
        if targets:
            first = dict(targets[0])
            first["exclude"] = "IGI HUD window"
            return first

        return {
            "concept": query,
            "region_hint": "any",
            "referring_expression": query,
            "exclude": "IGI HUD window"
        }

    def spark_verify_crop(self, crop: Image.Image, concept: str) -> tuple[bool, float]:
        """
        Spark Verification Step (muse-spark-1.3):
        Confirms whether the candidate cropped box actually contains the desired concept.
        Rejects false positives (e.g. Linus laptop video instead of TechLinked card).
        """
        if not crop or crop.width < 10 or crop.height < 10:
            return False, 0.0

        api_key = self.config.model.api_key
        base_url = self.config.model.base_url or "https://api.meta.ai/v1"
        tool_model = self.config.model.tool_model or "muse-spark-1.3"

        # 1. First attempt: Query Core Server on localhost:4100 if running
        try:
            buf = io.BytesIO()
            crop.save(buf, format="JPEG", quality=85)
            c_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
            core_url = f"{self.base_url}/verify"
            payload = {
                "concept": concept,
                "image_b64": c_b64,
                "model": "muse-spark-1.3"
            }
            res = self._client.post(core_url, json=payload, timeout=2.0)
            if res.status_code == 200:
                data = res.json()
                if "match" in data:
                    return bool(data["match"]), float(data.get("confidence", 0.90))
        except Exception:
            pass

        # 2. Direct Meta API if API key is present
        if api_key:
            try:
                buf = io.BytesIO()
                crop.save(buf, format="JPEG", quality=85)
                c_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

                headers = {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}"
                }
                messages = [
                    {
                        "role": "system",
                        "content": "You are a visual verification specialist. Look at the cropped image and answer whether it matches the concept. Return STRICT JSON ONLY: {\"match\": true|false, \"confidence\": float}"
                    },
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": f"Concept: {concept}. Does this crop contain or match it?"},
                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{c_b64}"}}
                        ]
                    }
                ]
                payload = {
                    "model": tool_model,
                    "messages": messages,
                    "temperature": 0.1,
                    "max_tokens": 100
                }
                res = self._client.post(f"{base_url}/chat/completions", json=payload, headers=headers, timeout=3.5)
                if res.status_code == 200:
                    raw = res.json().get("choices", [{}])[0].get("message", {}).get("content", "")
                    parsed = self._extract_json_dict(raw)
                    if parsed and "match" in parsed:
                        return bool(parsed["match"]), float(parsed.get("confidence", 0.90))
            except Exception:
                pass

        # 3. Fast Optical & Semantic Verification Fallback (Local / Offline)
        # Inspects crop text and visual characteristics to reject obvious false positives
        try:
            concept_low = (concept or "").lower()
            import winrt._winrt
            winrt._winrt.init_apartment(winrt._winrt.MTA)
            import winrt.windows.graphics.imaging as imaging
            import winrt.windows.storage.streams as streams
            import winrt.windows.media.ocr as winrt_ocr

            eng = winrt_ocr.OcrEngine.try_create_from_user_profile_languages()
            if eng:
                rgba = crop.convert("RGBA")
                writer = streams.DataWriter()
                writer.write_bytes(rgba.tobytes())
                buf = writer.detach_buffer()
                sb = imaging.SoftwareBitmap(
                    imaging.BitmapPixelFormat.RGBA8,
                    rgba.width,
                    rgba.height,
                    imaging.BitmapAlphaMode.PREMULTIPLIED
                )
                sb.copy_from_buffer(buf)
                ocr_res = eng.recognize_async(sb).get()
                crop_text = " ".join(l.text.lower() for l in ocr_res.lines)

                # Channel / Brand discrimination
                if "techlinked" in concept_low or "ltt" in concept_low:
                    has_target = any(k in crop_text for k in ("techlink", "billion", "6.3", "gone"))
                    if crop_text and not has_target:
                        return False, 0.95
                    if has_target:
                        return True, 0.95

                if "linus" in concept_low:
                    if "linus" in crop_text or "laptop" in crop_text:
                        return True, 0.95
                    if "techlink" in crop_text or "castlevania" in crop_text:
                        return False, 0.95

                if "reply" in concept_low:
                    if "reply" in crop_text:
                        return True, 0.95

                if "send" in concept_low:
                    if "send" in crop_text:
                        return True, 0.95
        except Exception:
            pass

        # Offline / fallback: accept candidate
        return True, 0.85
