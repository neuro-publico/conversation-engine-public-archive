"""Service for generating and editing landing page sections as HTML+Tailwind.

Follows the same architecture as ``section_image_service.py`` (the proven
blueprint for direct-provider services in this repo) but outputs HTML text
instead of images.  Zero LangChain — calls Gemini directly via
``app.externals.ai_direct.gemini_text.call_gemini_freeform``.
"""

import asyncio
import logging
import os
import re
import time
from typing import List, Optional

from app.db.audit_logger import log_prompt
from app.externals.ai_direct.gemini_text import GeminiTextError, call_gemini_freeform
from app.externals.ai_direct.gemini_text_v2 import (
    GeminiTextV2Error,
    call_gemini_freeform_v2,
)
from app.prompts.section_html_prompts import (
    PROMPT_AGENT_ID_HTML_EDIT_SYSTEM,
    PROMPT_AGENT_ID_HTML_GENERATE_SYSTEM,
    PROMPT_AGENT_ID_HTML_IMAGE_ORCHESTRATOR,
    PROMPT_AGENT_ID_HTML_TEMPLATE_STUDIO,
)
from app.requests.edit_section_html_request import EditSectionHtmlRequest
from app.requests.orchestrate_images_request import (
    OrchestratedImagePrompt,
    OrchestrateImagesRequest,
    OrchestrateImagesResponse,
)
from app.requests.section_html_request import SectionHtmlRequest
from app.requests.sub_image_request import GenerateSubImagesRequest, SubImageItem
from app.responses.section_html_response import SectionHtmlResponse
from app.services.prompt_config_service import PromptConfigService
from app.services.sub_image_service import (
    SUB_IMAGE_DELAY_AFTER_ATTEMPT,
    SUB_IMAGE_FALLBACK_MODEL,
    SUB_IMAGE_FALLBACK_PROVIDER,
    SUB_IMAGE_MAX_RETRIES,
)
from app.services.sub_image_service import SUB_IMAGE_MODEL as _SIM
from app.services.sub_image_service import SUB_IMAGE_RETRY_DELAY_SECONDS

logger = logging.getLogger(__name__)

DEFAULT_MODEL = os.environ.get("SECTION_HTML_MODEL", "gemini-3.1-pro-preview")
FALLBACK_MODEL = os.environ.get("SECTION_HTML_FALLBACK_MODEL", "gemini-3.1-pro-preview")
IMAGE_MODEL = os.environ.get("SECTION_IMAGE_MODEL", "gemini-3.1-flash-image-preview")
ORCHESTRATOR_MODEL = FALLBACK_MODEL
TEMPERATURE = 1.0  # Gemini 3 recommended default


class SectionHtmlService:
    """Generates and edits HTML landing page sections using Gemini directly."""

    # ------------------------------------------------------------------
    # PREVIEW: show exactly what the AI would receive (no AI call)
    # ------------------------------------------------------------------

    async def preview_prompt(
        self,
        template_html: Optional[str] = None,
        copy_prompt: Optional[str] = None,
        content_rules: Optional[str] = None,
        template_notes: Optional[str] = None,
        image_instructions: Optional[str] = None,
    ) -> dict:
        """Build the full prompt with abstract placeholders. Uses the REAL _build_generate_prompt."""
        request = SectionHtmlRequest(
            product_name="[Nombre del producto]",
            product_description="[Descripción del producto]",
            product_image_url="[URL imagen del producto]",
            product_images=["[Imagen producto 1]", "[Imagen producto 2]", "[Imagen producto 3]"],
            template_html=template_html or None,
            copy_prompt=copy_prompt or None,
            content_rules=content_rules or None,
            template_notes=template_notes or None,
            context="[Contexto generado automáticamente del análisis del producto]" if False else None,  # disabled
            sale_angle_name="[Ángulo de venta seleccionado]",
            sale_angle_description="[Descripción del ángulo de venta]",
            price_formatted="[Precio de venta formateado]",
            price_fake_formatted="[Precio original formateado]",
            brand_colors=["[Color primario]", "[Color secundario]"],
            language="[Idioma del usuario]",
            owner_id="preview",
        )

        user_prompt = self._build_generate_prompt(request)

        # Extract which blocks are active by checking what sections appear
        blocks = []
        if "TEMPLATE HTML" in user_prompt:
            blocks.append("Template HTML")
        if "COPY INSTRUCTIONS" in user_prompt:
            blocks.append("Instrucciones de copy")
        if "CONTENT RULES" in user_prompt:
            blocks.append("Reglas de contenido")
        if "NOTES FOR THIS" in user_prompt:
            blocks.append("Notas del template")
        if "PRODUCT:" in user_prompt:
            blocks.append("Producto (nombre + descripción)")
        if "PRODUCT CONTEXT" in user_prompt:
            blocks.append("Contexto del producto")
        if "PRODUCT IMAGES" in user_prompt or "PRODUCT IMAGE:" in user_prompt:
            blocks.append("Imágenes del producto")
        if "SALES ANGLE" in user_prompt:
            blocks.append("Ángulo de venta")
        if "PRICING" in user_prompt:
            blocks.append("Precios")
        if "BRAND COLORS" in user_prompt:
            blocks.append("Colores de marca")
        if "CSS VARIABLES" in user_prompt:
            blocks.append("Variables CSS")
        if "ADDITIONAL INSTRUCTIONS" in user_prompt:
            blocks.append("Instrucciones adicionales")
        if "LANGUAGE" in user_prompt:
            blocks.append("Idioma")

        # Resolve the current system prompt from agent-config (falls back to
        # the hardcoded FALLBACK_GENERATE_SYSTEM_PROMPT if unreachable). The
        # preview should reflect what would actually run now.
        system_prompt = await PromptConfigService.get(PROMPT_AGENT_ID_HTML_GENERATE_SYSTEM)

        return {
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "blocks": blocks,
            "models": {
                "html_generation": DEFAULT_MODEL,
                "html_generation_fallback": FALLBACK_MODEL,
                "image_orchestrator": ORCHESTRATOR_MODEL,
                "image_generation": IMAGE_MODEL,
                "image_fallback": f"{SUB_IMAGE_FALLBACK_PROVIDER}/{SUB_IMAGE_FALLBACK_MODEL}",
                "template_studio_editing": FALLBACK_MODEL,
            },
            "retries": {
                "image_max_retries": SUB_IMAGE_MAX_RETRIES,
                "image_delay_after_attempt": SUB_IMAGE_DELAY_AFTER_ATTEMPT,
                "image_retry_delay_seconds": SUB_IMAGE_RETRY_DELAY_SECONDS,
            },
            "temperature": TEMPERATURE,
        }

    # ------------------------------------------------------------------
    # GENERATE: template + product → personalised HTML
    # ------------------------------------------------------------------

    async def generate_section_html(self, request: SectionHtmlRequest) -> SectionHtmlResponse:
        t_start = time.monotonic()

        try:
            return await self._do_generate(request, t_start)
        except Exception:
            # Fallback to a more capable model
            try:
                logger.info("[SECTION_HTML] Primary failed, trying fallback model: %s", FALLBACK_MODEL)
                return await self._do_generate(request, t_start, model_override=FALLBACK_MODEL)
            except Exception as fallback_err:
                elapsed = int((time.monotonic() - t_start) * 1000)
                asyncio.create_task(
                    log_prompt(
                        log_type="section_html",
                        prompt=self._build_generate_prompt(request)[:2000],
                        owner_id=request.owner_id,
                        status="error",
                        error_message=str(fallback_err)[:500],
                        elapsed_ms=elapsed,
                    )
                )
                raise

    async def _do_generate(
        self, request: SectionHtmlRequest, t_start: float, model_override: Optional[str] = None
    ) -> SectionHtmlResponse:
        prompt = self._build_generate_prompt(request)
        model = model_override or DEFAULT_MODEL
        system_prompt = await PromptConfigService.get(PROMPT_AGENT_ID_HTML_GENERATE_SYSTEM)

        raw_response = await call_gemini_freeform(
            model=model,
            system_prompt=system_prompt,
            user_message=prompt,
            temperature=TEMPERATURE,
            max_output_tokens=14336,
            thinking_level="Low",
        )

        html = self._extract_html(raw_response)
        elapsed = int((time.monotonic() - t_start) * 1000)

        asyncio.create_task(
            log_prompt(
                log_type="section_html",
                prompt=prompt[:2000],
                owner_id=request.owner_id,
                model=model,
                provider="gemini",
                status="success",
                elapsed_ms=elapsed,
                metadata={
                    "section_role": request.section_role,
                    "html_length": len(html),
                    "had_template": bool(request.template_html),
                },
            )
        )

        return SectionHtmlResponse(html_content=html, model_used=model)

    # ------------------------------------------------------------------
    # EDIT: current HTML + user instruction → modified HTML
    # ------------------------------------------------------------------

    async def edit_section_html(self, request: EditSectionHtmlRequest) -> SectionHtmlResponse:
        t_start = time.monotonic()
        prompt = self._build_edit_prompt(request)
        model = DEFAULT_MODEL

        # Build conversation history in Gemini format
        history = None
        if request.conversation_history:
            history = [
                {
                    "role": "model" if msg.role == "assistant" else msg.role,
                    "text": msg.content,
                }
                for msg in request.conversation_history
            ]

        try:
            # Resolve the system prompt from agent-config (60s TTL cache +
            # hardcoded fallback). This is the dynamic-config pattern — the
            # prompt can be iterated in the DB without a deploy.
            system_prompt = await PromptConfigService.get(PROMPT_AGENT_ID_HTML_EDIT_SYSTEM)

            # v2 uses the official google-genai SDK + Interactions API with
            # streaming. Streaming avoids the ~60s server-side disconnect we
            # hit with the legacy generateContent when thinking + output
            # exceeded the window. `thinking_level="low"` (lowercase, per
            # official docs) keeps thought tokens minimal for HTML work.
            v2_result = await call_gemini_freeform_v2(
                model=model,
                system_prompt=system_prompt,
                user_message=prompt,
                conversation_history=history,
                temperature=TEMPERATURE,
                max_output_tokens=32768,
                thinking_level="low",
            )
            raw_response = v2_result["text"]
            v2_usage = v2_result.get("usage") or {}
            v2_interaction_id = v2_result.get("interaction_id")

            html = self._extract_html(raw_response)

            # If the AI introduced new placeholder images (or external URLs we
            # need to replace), generate them with the image pipeline before
            # returning. This mirrors what the CREATE flow already does.
            html = await self._process_new_images_in_edit(
                previous_html=request.current_html or "",
                new_html=html,
                request=request,
            )

            elapsed = int((time.monotonic() - t_start) * 1000)

            # Completeness check — catches mid-output token-limit truncation.
            # If input starts with `<section` but output doesn't close it,
            # the AI ran out of tokens and returned a broken HTML fragment
            # that would corrupt the section if accepted.
            input_html = request.current_html or ""
            if input_html.lstrip().startswith("<section") and "</section>" not in html:
                asyncio.create_task(
                    log_prompt(
                        log_type="section_html_edit",
                        prompt=prompt,
                        response_text=raw_response,
                        owner_id=request.owner_id,
                        model=model,
                        provider="gemini",
                        status="error",
                        error_message="AI output truncated (no </section>)",
                        elapsed_ms=elapsed,
                        metadata={
                            "instruction": request.instruction,
                            "current_html": request.current_html,
                            "extracted_html": html,
                            "truncation_detected": True,
                        },
                    )
                )
                raise Exception(
                    "La respuesta del AI quedó incompleta (demasiado larga). " "Intenta con un cambio más específico."
                )

            # Full audit log: everything sent to Gemini + raw reply + metadata.
            # Lets us replay/diagnose any edit that looked wrong to the user.
            asyncio.create_task(
                log_prompt(
                    log_type="section_html_edit",
                    prompt=prompt,
                    response_text=raw_response,
                    owner_id=request.owner_id,
                    model=model,
                    provider="gemini",
                    status="success",
                    elapsed_ms=elapsed,
                    metadata={
                        "instruction": request.instruction,
                        "product_name": request.product_name,
                        "language": request.language,
                        "system_prompt": system_prompt,
                        "current_html": request.current_html,
                        "extracted_html": html,
                        "input_html_length": len(request.current_html or ""),
                        "output_html_length": len(html),
                        "raw_response_length": len(raw_response or ""),
                        "history_turns": len(request.conversation_history or []),
                        "conversation_history": [
                            {"role": m.role, "content": m.content} for m in (request.conversation_history or [])
                        ],
                        "sdk": "v2_interactions_streaming",
                        "interaction_id": v2_interaction_id,
                        "usage": v2_usage,
                    },
                )
            )

            return SectionHtmlResponse(html_content=html, model_used=model)

        except Exception as e:
            elapsed = int((time.monotonic() - t_start) * 1000)
            asyncio.create_task(
                log_prompt(
                    log_type="section_html_edit",
                    prompt=prompt,
                    owner_id=request.owner_id,
                    model=model,
                    provider="gemini",
                    status="error",
                    error_message=str(e)[:1000],
                    elapsed_ms=elapsed,
                    metadata={
                        "instruction": request.instruction,
                        "current_html": request.current_html,
                        # If we failed before resolving the system prompt, log the
                        # agent_id instead so ops can cross-check agent-config.
                        "system_prompt_agent_id": PROMPT_AGENT_ID_HTML_EDIT_SYSTEM,
                    },
                )
            )
            raise

    # ------------------------------------------------------------------
    # TEMPLATE STUDIO: generate/iterate template HTML via chat
    # ------------------------------------------------------------------

    async def generate_template_html(
        self,
        instruction: str,
        conversation_history: Optional[List[dict]] = None,
        owner_id: str = "",
    ) -> SectionHtmlResponse:
        t_start = time.monotonic()
        model = FALLBACK_MODEL  # Use Pro for template studio editing (higher quality)

        history = None
        if conversation_history:
            history = [
                {
                    "role": "model" if msg.get("role") == "assistant" else msg.get("role", "user"),
                    "text": msg.get("content", ""),
                }
                for msg in conversation_history
            ]

        try:
            system_prompt = await PromptConfigService.get(PROMPT_AGENT_ID_HTML_TEMPLATE_STUDIO)

            raw_response = await call_gemini_freeform(
                model=model,
                system_prompt=system_prompt,
                user_message=instruction,
                conversation_history=history,
                temperature=TEMPERATURE,
                max_output_tokens=14336,
                thinking_level="Low",
            )

            html = self._extract_html(raw_response)
            elapsed = int((time.monotonic() - t_start) * 1000)

            asyncio.create_task(
                log_prompt(
                    log_type="template_studio",
                    prompt=instruction[:1000],
                    owner_id=owner_id,
                    model=model,
                    provider="gemini",
                    status="success",
                    elapsed_ms=elapsed,
                    metadata={"html_length": len(html)},
                )
            )

            return SectionHtmlResponse(html_content=html, model_used=model)

        except Exception as e:
            elapsed = int((time.monotonic() - t_start) * 1000)
            asyncio.create_task(
                log_prompt(
                    log_type="template_studio",
                    prompt=instruction[:1000],
                    owner_id=owner_id,
                    status="error",
                    error_message=str(e)[:500],
                    elapsed_ms=elapsed,
                )
            )
            raise

    # ------------------------------------------------------------------
    # ORCHESTRATE IMAGE PROMPTS
    # ------------------------------------------------------------------

    async def orchestrate_image_prompts(self, request: OrchestrateImagesRequest) -> OrchestrateImagesResponse:
        """Analyze HTML, find placeholder images, generate coherent prompts for all of them."""
        t_start = time.monotonic()

        # Count placeholder images
        placeholder_count = request.html_content.count("placehold.co")
        if placeholder_count == 0:
            return OrchestrateImagesResponse(prompts=[])

        prompt = self._build_orchestrate_prompt(request, placeholder_count)

        try:
            system_prompt = await PromptConfigService.get(PROMPT_AGENT_ID_HTML_IMAGE_ORCHESTRATOR)

            raw_response = await call_gemini_freeform(
                model=ORCHESTRATOR_MODEL,
                system_prompt=system_prompt,
                user_message=prompt,
                temperature=0.7,
                max_output_tokens=14336,
                thinking_level="Low",
            )

            prompts = self._parse_orchestrated_prompts(raw_response, placeholder_count)

            asyncio.create_task(
                log_prompt(
                    log_type="orchestrate_images",
                    prompt=prompt[:1000],
                    owner_id=request.owner_id,
                    model=DEFAULT_MODEL,
                    provider="gemini",
                    status="success",
                    elapsed_ms=int((time.monotonic() - t_start) * 1000),
                    metadata={"placeholder_count": placeholder_count, "prompts_generated": len(prompts)},
                )
            )

            return OrchestrateImagesResponse(prompts=prompts)

        except Exception as e:
            logger.error(f"Image orchestration failed: {e}")
            asyncio.create_task(
                log_prompt(
                    log_type="orchestrate_images",
                    prompt=prompt[:1000],
                    owner_id=request.owner_id,
                    status="error",
                    error_message=str(e)[:500],
                    elapsed_ms=int((time.monotonic() - t_start) * 1000),
                )
            )
            return OrchestrateImagesResponse(prompts=[])

    # ------------------------------------------------------------------
    # PROMPT BUILDERS
    # ------------------------------------------------------------------

    def _build_generate_prompt(self, request: SectionHtmlRequest) -> str:
        parts: list[str] = []

        # Template
        if request.template_html:
            parts.append(f"TEMPLATE HTML (follow this design):\n{request.template_html}")

        # Copy instructions (detailed copywriting prompt from agent-config)
        if request.copy_prompt:
            parts.append(f"COPY INSTRUCTIONS (follow these for writing all text content):\n{request.copy_prompt}")

        # Content rules (brief structural rules)
        if request.content_rules:
            parts.append(f"CONTENT RULES FOR THIS SECTION TYPE:\n{request.content_rules}")

        # Template-specific notes
        if request.template_notes:
            parts.append(f"NOTES FOR THIS SPECIFIC TEMPLATE:\n{request.template_notes}")

        # Product
        parts.append(f"PRODUCT:\n- Name: {request.product_name}\n- Description: {request.product_description}")

        # Product context (detailed info from scraping/analysis)
        if request.context:
            parts.append(f"PRODUCT CONTEXT (use this as the foundation for all copy):\n{request.context}")

        # Images
        if request.product_images:
            img_list = "\n".join(f"  - {url}" for url in request.product_images)
            parts.append(f"PRODUCT IMAGES (use these real URLs in img tags):\n{img_list}")
        elif request.product_image_url:
            parts.append(f"PRODUCT IMAGE: {request.product_image_url}")

        # Sales angle
        if request.sale_angle_name:
            angle = f"SALES ANGLE:\n- Name: {request.sale_angle_name}"
            if request.sale_angle_description:
                angle += f"\n- Description: {request.sale_angle_description}"
            angle += "\n- Adapt ALL text to this sales angle's tone and messaging."
            parts.append(angle)

        # Pricing
        def _clean_price(p: str) -> str:
            return re.sub(r"[,.]00$", "", p) if p else p

        if request.price_formatted:
            price_block = "PRICING (use these EXACT values, do not change format):"
            if request.price_fake_formatted:
                price_block += f"\n- Original price (crossed out): {_clean_price(request.price_fake_formatted)}"
            price_block += f"\n- Sale price (prominent): {_clean_price(request.price_formatted)}"
            parts.append(price_block)
        elif request.price is not None:
            price_block = "PRICING:"
            if request.price_fake is not None:
                price_block += f"\n- Original price (crossed out): ${request.price_fake:,.0f}"
            price_block += f"\n- Sale price (prominent): ${request.price:,.0f}"
            parts.append(price_block)

        # Brand colors
        if request.brand_colors:
            colors_str = ", ".join(request.brand_colors)
            parts.append(
                f"BRAND COLORS: {colors_str}\n"
                "Use these to influence the overall tone. Use var(--brand-primary) for accents."
            )

        # CSS Variables
        if request.style_variables:
            vars_str = "\n".join(f"  {k}: {v};" for k, v in request.style_variables.items())
            parts.append(f"CSS VARIABLES (the page defines these, use them):\n{vars_str}")

        # Extra instructions
        if request.user_instructions:
            parts.append(f"ADDITIONAL INSTRUCTIONS:\n{request.user_instructions}")

        # Language
        parts.append(f"LANGUAGE: All text must be in {request.language}.")

        return "\n\n".join(parts)

    def _build_edit_prompt(self, request: EditSectionHtmlRequest) -> str:
        parts: list[str] = []

        parts.append(f"CURRENT HTML OF THE SECTION:\n{request.current_html}")
        parts.append(f"USER'S INSTRUCTION:\n{request.instruction}")
        parts.append(f"PRODUCT CONTEXT: {request.product_name} — {request.product_description}")

        if request.style_variables:
            vars_str = "\n".join(f"  {k}: {v};" for k, v in request.style_variables.items())
            parts.append(f"CSS VARIABLES:\n{vars_str}")

        parts.append(f"LANGUAGE: {request.language}")

        return "\n\n".join(parts)

    # ------------------------------------------------------------------
    # HTML EXTRACTION
    # ------------------------------------------------------------------

    def _build_orchestrate_prompt(self, request: OrchestrateImagesRequest, count: int) -> str:
        parts = []
        parts.append(f"HTML OF THE SECTION (contains {count} placeholder images to replace):")
        parts.append(request.html_content)
        parts.append(f"\nPRODUCT: {request.product_name} — {request.product_description}")

        if request.sale_angle_name:
            parts.append(f"SALES ANGLE: {request.sale_angle_name}")

        if request.image_instructions:
            parts.append(f"\nIMAGE INSTRUCTIONS FROM TEMPLATE CREATOR:\n{request.image_instructions}")

        parts.append(f"\nLANGUAGE: {request.language}")
        parts.append(
            f"\nGenerate exactly {count} image prompts — one for each placeholder image in the HTML, in order of appearance."
        )

        return "\n\n".join(parts)

    @staticmethod
    def _parse_orchestrated_prompts(raw: str, expected_count: int) -> list:
        """Parse AI response into list of OrchestratedImagePrompt."""
        import json as json_module

        text = raw.strip()

        # Try JSON array
        try:
            match = re.search(r"\[.*\]", text, re.DOTALL)
            if match:
                data = json_module.loads(match.group())
                return [
                    OrchestratedImagePrompt(
                        prompt=item.get("prompt", item) if isinstance(item, dict) else str(item),
                        aspect_ratio=item.get("aspect_ratio", "1:1") if isinstance(item, dict) else "1:1",
                    )
                    for item in data
                ]
        except (json_module.JSONDecodeError, AttributeError):
            pass

        # Fallback: split by numbered lines (1. ..., 2. ..., etc.)
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        prompts = []
        for line in lines:
            cleaned = re.sub(r"^\d+[\.\)\-]\s*", "", line)
            if cleaned and len(cleaned) > 10:
                prompts.append(OrchestratedImagePrompt(prompt=cleaned))

        return prompts[:expected_count] if prompts else []

    @staticmethod
    def _extract_html(raw_response: str) -> str:
        """Extract clean HTML from Gemini response.

        Gemini *should* return only HTML (per system prompt), but sometimes
        wraps it in markdown code blocks or adds explanatory text.  This
        method handles all observed patterns.
        """
        text = raw_response.strip()

        # Case 1: markdown code block
        match = re.search(r"```html?\s*\n(.*?)```", text, re.DOTALL)
        if match:
            return match.group(1).strip()

        # Case 2: text before/after the HTML — find the outermost section/div
        match = re.search(
            r"(<(?:section|div|article|header|main|aside|footer|nav)\b.*"
            r"</(?:section|div|article|header|main|aside|footer|nav)>)",
            text,
            re.DOTALL,
        )
        if match:
            return match.group(1).strip()

        # Case 3: already clean HTML
        if text.startswith("<"):
            return text

        # Case 4: could not extract — return as-is and let the caller deal with it
        logger.warning(
            "[SECTION_HTML] Could not extract clean HTML. First 200 chars: %s",
            text[:200],
        )
        return text

    # ------------------------------------------------------------------
    # IMAGE PIPELINE FOR EDITS
    # ------------------------------------------------------------------

    # Domains we trust as "real" already-generated images — never regenerate.
    _TRUSTED_IMAGE_HOSTS = (
        "fluxi.co",
        "fluxi.s3.amazonaws.com",
        "d39ru7awumhhs2.cloudfront.net",
        "d3a0hisq8b5pnu.cloudfront.net",
    )

    _IMG_SRC_RE = re.compile(r'<img[^>]*\ssrc\s*=\s*(["\'])([^"\']+)\1', re.IGNORECASE)

    @classmethod
    def _extract_img_srcs(cls, html: str) -> List[str]:
        """Return the ordered list of `<img src="...">` URLs in `html`."""
        return [m.group(2) for m in cls._IMG_SRC_RE.finditer(html)]

    @classmethod
    def _is_trusted_image(cls, url: str) -> bool:
        return any(host in url for host in cls._TRUSTED_IMAGE_HOSTS)

    @classmethod
    def _is_placeholder(cls, url: str) -> bool:
        return "placehold.co" in url

    @classmethod
    def _url_to_placeholder(cls, url: str, alt_text: str = "image") -> str:
        """Convert an untrusted external URL into a placehold.co URL so the
        image pipeline can regenerate it. We keep a stable size (400x400) —
        the orchestrator reads the surrounding context, not the placeholder
        dimensions, to decide what each image should show."""
        import urllib.parse as _urllib

        safe = _urllib.quote_plus(alt_text or "image")
        return f"https://placehold.co/400x400/EEE/999?text={safe}"

    def _sanitize_image_urls(self, previous_html: str, new_html: str) -> str:
        """Replace any external, non-trusted, non-placehold.co URL the AI
        introduced with a placehold.co URL so the pipeline generates a
        contextual image instead of shipping a random external one.

        Existing trusted URLs (already present in `previous_html`) are kept
        as-is — only NEW suspicious URLs get rewritten.
        """
        previous_srcs = set(self._extract_img_srcs(previous_html))

        def _replace(match: "re.Match[str]") -> str:
            quote = match.group(1)
            url = match.group(2)
            if url in previous_srcs:
                # Kept from the input — the AI preserved an existing image.
                return match.group(0)
            if self._is_trusted_image(url) or self._is_placeholder(url):
                return match.group(0)
            # Try to use the alt text as the placeholder description.
            start = match.end()
            tail = new_html[start : start + 200]
            alt_match = re.search(r'alt\s*=\s*(["\'])([^"\']*)\1', tail, re.IGNORECASE)
            alt_text = alt_match.group(2) if alt_match else "imagen"
            logger.info(
                "[EDIT_IMAGES] Replacing untrusted URL with placeholder. url=%s alt=%s",
                url[:80],
                alt_text[:80],
            )
            placeholder = self._url_to_placeholder(url, alt_text)
            # Preserve the rest of the <img ... > tag (alt, class, etc.).
            return match.group(0).replace(url, placeholder)

        return self._IMG_SRC_RE.sub(_replace, new_html)

    async def _process_new_images_in_edit(
        self,
        *,
        previous_html: str,
        new_html: str,
        request: EditSectionHtmlRequest,
    ) -> str:
        """Generate real images for any NEW placehold.co placeholders the AI
        introduced during an edit. Returns the HTML with S3 URLs replacing
        those placeholders.

        Graceful degradation: if orchestrator or image generator fails we
        return the HTML unchanged (placeholders stay visible as gray boxes —
        better than an error that blocks the user's edit).
        """
        # 1) Normalize untrusted external URLs into placeholders first.
        normalized_html = self._sanitize_image_urls(previous_html, new_html)

        # 2) Which placeholders are NEW (not present in the input already)?
        previous_placeholders = [u for u in self._extract_img_srcs(previous_html) if self._is_placeholder(u)]
        current_placeholders = [u for u in self._extract_img_srcs(normalized_html) if self._is_placeholder(u)]
        previous_set = set(previous_placeholders)
        new_placeholders = [u for u in current_placeholders if u not in previous_set]

        if not new_placeholders:
            return normalized_html

        logger.info(
            "[EDIT_IMAGES] Found %d new placeholders to generate (out of %d total in output)",
            len(new_placeholders),
            len(current_placeholders),
        )

        # 3) Ask the orchestrator to generate a coherent prompt for EACH
        # placeholder in the current HTML (it reads surrounding context).
        # We pass the full HTML + funnel/template context so new images
        # match the visual style of the rest of the page (same rules the
        # CREATE flow uses in ecommerce-service).
        try:
            orch_request = OrchestrateImagesRequest(
                html_content=normalized_html,
                image_instructions=request.image_instructions,
                product_name=request.product_name or "",
                product_description=request.product_description or "Product",
                product_image_url=request.product_image_url,
                sale_angle_name=request.sale_angle_name,
                language=request.language or "es",
                owner_id=request.owner_id,
            )
            orch_response = await self.orchestrate_image_prompts(orch_request)
            if not orch_response.prompts:
                logger.warning("[EDIT_IMAGES] Orchestrator returned 0 prompts; skipping generation")
                return normalized_html
        except Exception as e:
            logger.exception("[EDIT_IMAGES] Orchestrator failed; leaving placeholders in place: %s", e)
            return normalized_html

        # 4) Generate the sub-images. The orchestrator returns prompts in the
        # same order as placeholders appear in the HTML. We only generate for
        # indices that correspond to NEW placeholders (the rest already have
        # real URLs or are untouched placeholders we shouldn't change).
        try:
            from app.services.sub_image_service import SubImageService

            sub_image_service = SubImageService()

            # Build sub-image items only for NEW placeholders.
            items: List[SubImageItem] = []
            # Map current placeholder index → prompt from orchestrator.
            prompts_by_idx = {i: p for i, p in enumerate(orch_response.prompts)}
            new_indices = [i for i, u in enumerate(current_placeholders) if u not in previous_set]
            for i in new_indices:
                if i not in prompts_by_idx:
                    continue
                p = prompts_by_idx[i]
                items.append(
                    SubImageItem(
                        id=f"edit_img_{i}",
                        prompt=p.prompt,
                        aspect_ratio=p.aspect_ratio or "1:1",
                    )
                )
            if not items:
                return normalized_html

            sub_request = GenerateSubImagesRequest(
                images=items,
                product_name=request.product_name or "",
                product_description=request.product_description or "Product",
                product_image_url=request.product_image_url,
                product_images=request.product_images,
                language=request.language or "es",
                sale_angle_name=request.sale_angle_name,
                brand_colors=request.brand_colors,
                owner_id=request.owner_id,
            )
            sub_response = await sub_image_service.generate_sub_images(sub_request)
            generated = sub_response.images or {}
        except Exception as e:
            logger.exception("[EDIT_IMAGES] Sub-image generation failed; keeping placeholders: %s", e)
            return normalized_html

        # 5) Replace NEW placeholders in order with their generated S3 URLs.
        # We walk the HTML replacing only the Nth match that corresponds to a
        # new placeholder — preserving existing trusted URLs and untouched
        # placeholders.
        final_html = normalized_html
        # Walk in reverse by original index so replace positions stay stable.
        for i in new_indices:
            item_id = f"edit_img_{i}"
            s3_url = generated.get(item_id)
            if not s3_url:
                continue
            placeholder_url = current_placeholders[i]
            # Replace FIRST occurrence of this URL (there may be duplicates but
            # we only want to swap the one at position i — reverse order keeps
            # earlier matches unaffected).
            final_html = final_html.replace(placeholder_url, s3_url, 1)

        return final_html
