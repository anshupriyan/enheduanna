"""
Local Open-Source OCR Engine for mem-vision-mcp.
Primary: Windows Native WinRT OCR (hardware-accelerated, zero network, MIT license).
Fallback: pytesseract (Apache-2.0 license).
"""

from __future__ import annotations

import asyncio
import io
import logging
from typing import Optional
from PIL import Image

logger = logging.getLogger(__name__)


class LocalOCREngine:
    """
    On-device, privacy-preserving OCR engine.
    Extracts text from screenshots without sending a single byte over the network.
    """

    def __init__(self, primary_engine: str = "winrt", fallback_engine: str = "pytesseract", enabled: bool = True):
        self.primary_engine = primary_engine.lower()
        self.fallback_engine = fallback_engine.lower()
        self.enabled = enabled
        self._winrt_engine = None
        self._winrt_initialized = False
        self._init_winrt()

    def _init_winrt(self) -> None:
        """Initialize Windows native WinRT OCR engine."""
        try:
            import winrt.windows.media.ocr as winrt_ocr
            self._winrt_engine = winrt_ocr.OcrEngine.try_create_from_user_profile_languages()
            if self._winrt_engine:
                self._winrt_initialized = True
                logger.info("Windows Native WinRT OCR initialized successfully.")
            else:
                logger.warning("Windows Native WinRT OCR engine could not be created from user languages.")
        except Exception as e:
            logger.warning("Windows Native WinRT OCR initialization error: %s", e)
            self._winrt_initialized = False

    def extract_text(self, image: Image.Image) -> str:
        """
        Extract text synchronously from a PIL Image.
        Tries primary engine first, then falls back if configured.
        """
        if not self.enabled:
            return ""

        if self.primary_engine == "winrt" and self._winrt_initialized:
            try:
                text = self._ocr_winrt(image)
                if text is not None:
                    return text
            except Exception as e:
                logger.warning("WinRT OCR failed (%s); trying fallback %s", e, self.fallback_engine)

        if self.fallback_engine == "pytesseract":
            return self._ocr_tesseract(image)

        return ""

    def extract_text_and_lines(self, image: Image.Image) -> tuple[str, list[dict]]:
        """
        Extract full text and structured lines with bounding boxes from a PIL Image.
        Returns: (full_text, [{"text": line_text, "rect": [x, y, w, h], "words": [...]}])
        """
        if not self.enabled:
            return "", []

        if self.primary_engine == "winrt" and self._winrt_initialized:
            try:
                res = asyncio.run(self._ocr_winrt_lines_async(image))
                if res is not None:
                    return res
            except Exception as e:
                logger.warning("WinRT OCR lines failed (%s); trying fallback", e)

        if self.fallback_engine == "pytesseract":
            return self._ocr_tesseract_lines(image)

        txt = self.extract_text(image)
        lines = [{"text": l, "rect": [0, 0, image.width, 20], "words": []} for l in txt.splitlines() if l.strip()]
        return txt, lines

    def _ocr_winrt(self, image: Image.Image) -> Optional[str]:
        """Runs Windows Native WinRT OCR asynchronously via asyncio."""
        return asyncio.run(self._ocr_winrt_async(image))

    async def _ocr_winrt_async(self, image: Image.Image) -> Optional[str]:
        """Asynchronously decode image to WinRT SoftwareBitmap and run OcrEngine."""
        res = await self._ocr_winrt_lines_async(image)
        return res[0] if res else ""

    async def _ocr_winrt_lines_async(self, image: Image.Image) -> tuple[str, list[dict]]:
        """Extract both full text and structured line bounds using WinRT."""
        import winrt.windows.graphics.imaging as imaging
        import winrt.windows.storage.streams as streams

        # Convert PIL image to uncompressed BMP bytes for fastest decoder ingestion
        buf = io.BytesIO()
        image.save(buf, format="BMP")
        raw_bytes = buf.getvalue()

        writer = streams.DataWriter()
        writer.write_bytes(raw_bytes)
        ibuffer = writer.detach_buffer()

        stream = streams.InMemoryRandomAccessStream()
        await stream.write_async(ibuffer)
        stream.seek(0)

        decoder = await imaging.BitmapDecoder.create_async(stream)
        software_bitmap = await decoder.get_software_bitmap_async()

        result = await self._winrt_engine.recognize_async(software_bitmap)
        if not result or not result.text:
            return "", []

        full_text = result.text.strip()
        lines_data: list[dict] = []

        for line in result.lines:
            line_words = []
            min_x = 999999
            min_y = 999999
            max_x = 0
            max_y = 0
            for w in line.words:
                b = w.bounding_rect
                min_x = min(min_x, b.x)
                min_y = min(min_y, b.y)
                max_x = max(max_x, b.x + b.width)
                max_y = max(max_y, b.y + b.height)
                line_words.append({
                    "text": w.text,
                    "rect": [int(b.x), int(b.y), int(b.width), int(b.height)],
                })
            lw = max(0, int(max_x - min_x)) if min_x < 999999 else 0
            lh = max(0, int(max_y - min_y)) if min_y < 999999 else 0
            lines_data.append({
                "text": line.text,
                "rect": [int(min_x if min_x < 999999 else 0), int(min_y if min_y < 999999 else 0), lw, lh],
                "words": line_words,
            })

        return full_text, lines_data

    def _ocr_tesseract(self, image: Image.Image) -> str:
        """Fallback OCR using pytesseract."""
        try:
            import pytesseract
            text = pytesseract.image_to_string(image)
            return text.strip() if text else ""
        except Exception as e:
            logger.debug("pytesseract execution failed: %s", e)
            return ""

    def _ocr_tesseract_lines(self, image: Image.Image) -> tuple[str, list[dict]]:
        """Fallback line bounding extraction using pytesseract."""
        try:
            import pytesseract
            data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
            lines_map: dict[int, dict] = {}
            full_words = []
            n_boxes = len(data.get("text", []))
            for i in range(n_boxes):
                text = (data["text"][i] or "").strip()
                if not text:
                    continue
                full_words.append(text)
                line_num = data["line_num"][i]
                x = data["left"][i]
                y = data["top"][i]
                w = data["width"][i]
                h = data["height"][i]
                if line_num not in lines_map:
                    lines_map[line_num] = {
                        "words": [],
                        "min_x": x,
                        "min_y": y,
                        "max_x": x + w,
                        "max_y": y + h,
                    }
                lm = lines_map[line_num]
                lm["words"].append({"text": text, "rect": [x, y, w, h]})
                lm["min_x"] = min(lm["min_x"], x)
                lm["min_y"] = min(lm["min_y"], y)
                lm["max_x"] = max(lm["max_x"], x + w)
                lm["max_y"] = max(lm["max_y"], y + h)

            structured_lines = []
            for ln in sorted(lines_map.keys()):
                lm = lines_map[ln]
                words_text = " ".join(w["text"] for w in lm["words"])
                structured_lines.append({
                    "text": words_text,
                    "rect": [lm["min_x"], lm["min_y"], lm["max_x"] - lm["min_x"], lm["max_y"] - lm["min_y"]],
                    "words": lm["words"],
                })
            return " ".join(full_words), structured_lines
        except Exception as e:
            logger.debug("pytesseract lines failed: %s", e)
            txt = self._ocr_tesseract(image)
            return txt, []
