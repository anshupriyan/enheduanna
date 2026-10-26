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

    def _ocr_winrt(self, image: Image.Image) -> Optional[str]:
        """Runs Windows Native WinRT OCR asynchronously via asyncio."""
        return asyncio.run(self._ocr_winrt_async(image))

    async def _ocr_winrt_async(self, image: Image.Image) -> Optional[str]:
        """Asynchronously decode image to WinRT SoftwareBitmap and run OcrEngine."""
        import winrt.windows.graphics.imaging as imaging
        import winrt.windows.storage.streams as streams

        # Convert PIL image to uncompressed BMP bytes for fastest decoder ingestion
        buf = io.BytesIO()
        # Grayscale or RGB BMP
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
        return result.text.strip() if result and result.text else ""

    def _ocr_tesseract(self, image: Image.Image) -> str:
        """Fallback OCR using pytesseract."""
        try:
            import pytesseract
            text = pytesseract.image_to_string(image)
            return text.strip() if text else ""
        except Exception as e:
            logger.debug("pytesseract execution failed (tesseract may not be installed in PATH): %s", e)
            return ""
