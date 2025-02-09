from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import os
import re
from typing import Dict, Optional, Tuple
from urllib.parse import urlparse

import aiohttp
from fake_useragent import UserAgent
from pdf2image import convert_from_bytes
from PyPDF2 import PdfReader
from upstash_redis.asyncio import Redis

logger = logging.getLogger("sci.hub.scraper")


class SciHubScraper:
    """A scraper for retrieving papers from Sci-Hub."""

    def __init__(self) -> None:
        """Initialize the scraper with default headers and domains."""
        self.ua = UserAgent()
        self.base_headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
        }
        self.domains = [
            "https://sci-hub.ru",
            "https://sci-hub.st",
            "https://sci-hub.se",
        ]
        self.session: Optional[aiohttp.ClientSession] = None
        self.redis: Optional[Redis] = None
        self.payload = {
            "sci-hub-plugin-check": "",
            "request": "",
        }
        self.use_cache = os.environ.get("USE_CACHE", "true").lower() == "true"
        logger.info("SciHubScraper initialized")

    @property
    def headers(self) -> dict[str, str]:
        """Generate headers with a random user agent.

        Returns:
            dict[str, str]: Headers dictionary with random user agent.
        """
        return {**self.base_headers, "User-Agent": self.ua.random}

    async def init(self) -> None:
        """Initialize aiohttp session and Redis client if caching is enabled."""
        self.session = aiohttp.ClientSession()
        if self.use_cache:
            self.redis = Redis.from_env()
            logger.info("Redis client initialized")
        else:
            logger.info("Caching disabled")

    async def close(self) -> None:
        """Close aiohttp session if it exists."""
        if self.session:
            await self.session.close()
            self.session = None

    def extract_doi(self, text: str) -> Optional[str]:
        """Extract DOI from text using regex pattern.

        Args:
            text (str): Text containing potential DOI.

        Returns:
            Optional[str]: Extracted DOI or None if not found.
        """
        doi_pattern = r"\b(10\.\d{4,}/[-._;()/:\w]+)\b"
        if match := re.search(doi_pattern, text):
            return match.group(1)
        return None

    async def _make_request(
        self, url: str, context: str = "request", doi: str = None
    ) -> Optional[Tuple[int, str]]:
        """Make an HTTP request and log the response."""
        try:
            req_headers = self.headers.copy()
            if "sci-hub" in url:
                parsed = urlparse(url)
                domain = f"{parsed.scheme}://{parsed.netloc}"
                req_headers["Referer"] = domain

                payload = self.payload.copy()
                payload["request"] = doi
                async with self.session.post(
                    url, headers=req_headers, data=payload, timeout=10
                ) as response:
                    status = response.status
                    logger.info(f"{context} - Response {status} from {url}")
                    if status == 200:
                        return status, await response.text()
                    return status, ""
            else:
                async with self.session.get(
                    url, headers=req_headers, timeout=10
                ) as response:
                    status = response.status
                    logger.info(f"{context} - Response {status} from {url}")
                    if status == 200:
                        return status, await response.text()
                    return status, ""
        except aiohttp.ClientError as e:
            logger.error(f"{context} - Connection error for {url}: {str(e)}")
        except asyncio.TimeoutError:
            logger.error(f"{context} - Timeout accessing {url}")
        except Exception as e:
            logger.error(
                f"{context} - Unexpected error with {url}: {str(e)}", exc_info=True
            )
        return None

    async def get_paper_metadata(self, doi: str) -> Optional[Dict[str, str]]:
        """Get paper metadata from doi2bib."""
        if not self.session:
            raise RuntimeError("Session not initialized. Call init() first.")

        url = (
            f"https://www.doi2bib.org/8350e5a3e24c153df2275c9f80692773/doi2bib?id={doi}"
        )
        logger.debug(f"Fetching metadata for DOI: {doi}")

        result = await self._make_request(url, "Metadata", doi)
        if not result:
            return None

        status, bib_text = result
        if status == 200:
            metadata = self._parse_metadata(bib_text)
            if metadata:
                logger.info(f"Successfully parsed metadata for DOI: {doi}")
                return metadata
            logger.warning(f"No metadata found in response for DOI: {doi}")
        return None

    def _parse_metadata(self, bib_text: str) -> dict[str, str]:
        """Parse metadata from bib text."""
        metadata = {}
        patterns = {
            "title": r"title={([^}]+)}",
            "author": r"author={([^}]+)}",
            "journal": r"journal={([^}]+)}",
            "year": r"year={([^}]+)}",
            "publisher": r"publisher={([^}]+)}",
        }
        for key, pattern in patterns.items():
            if match := re.search(pattern, bib_text):
                metadata[key] = match.group(1)
        return metadata

    def extract_pdf_url(self, html: str, base_url: str) -> Optional[str]:
        """Extract PDF URL from Sci-Hub HTML content."""
        pdf_pattern = r'(?:src|href)=[\'"](?:/(?:downloads|tree|uptodate)/[^"\'>]+\.pdf|/[^"\'>]+\.pdf)'
        if match := re.search(pdf_pattern, html):
            pdf_path = match.group(0).split("=")[1].strip("\"'")

            if pdf_path.startswith("/downloads"):
                return f"{base_url}{pdf_path}"
            elif pdf_path.startswith("/tree"):
                return f"{base_url}{pdf_path}"
            elif pdf_path.startswith("/uptodate"):
                return f"{base_url}{pdf_path}"
            elif pdf_path.startswith("//"):
                return f"https:{pdf_path}"
            else:
                return f"{base_url}{pdf_path}"
        return None

    async def get_pdf_preview(self, pdf_url: str) -> Optional[io.BytesIO]:
        """Download PDF and convert first page to image."""
        try:
            async with self.session.get(pdf_url, headers=self.headers) as response:
                if response.status != 200:
                    return None

                pdf_content = await response.read()

                # create pdf reader
                pdf = PdfReader(io.BytesIO(pdf_content))
                if len(pdf.pages) == 0:
                    return None

                # convert first page to image
                images = convert_from_bytes(
                    pdf_content,
                    first_page=1,
                    last_page=1,
                    size=(800, None),
                )

                if not images:
                    return None

                # convert pillow image to bytes
                img_byte_arr = io.BytesIO()
                images[0].save(img_byte_arr, format="PNG")
                img_byte_arr.seek(0)

                return img_byte_arr

        except Exception as e:
            logger.error(f"Error generating PDF preview: {str(e)}", exc_info=True)
            return None

    async def get_cached_paper(
        self, doi: str
    ) -> Optional[Tuple[str, str, Dict, io.BytesIO]]:
        """Get paper data from cache if available and caching is enabled."""
        if not self.use_cache or not self.redis:
            return None

        try:
            cached = await self.redis.get(f"paper:{doi}")
            if not cached:
                return None

            data = json.loads(cached)
            preview = None
            if data.get("preview"):
                preview_bytes = base64.b64decode(data["preview"])
                preview = io.BytesIO(preview_bytes)

            return (data["pdf_url"], data["domain"], data["metadata"], preview)
        except Exception as e:
            logger.error(f"Error retrieving from cache: {str(e)}", exc_info=True)
            return None

    async def cache_paper(
        self,
        doi: str,
        pdf_url: str,
        domain: str,
        metadata: Dict,
        preview: Optional[io.BytesIO],
    ) -> None:
        """Cache paper data in Redis if caching is enabled."""
        if not self.use_cache or not self.redis:
            return

        try:
            cache_data = {
                "pdf_url": pdf_url,
                "domain": domain,
                "metadata": metadata,
                "preview": None,
            }

            if preview:
                preview_bytes = preview.getvalue()
                cache_data["preview"] = base64.b64encode(preview_bytes).decode()

            await self.redis.set(f"paper:{doi}", json.dumps(cache_data), ex=2592000)
            logger.info(f"Cached paper data for DOI: {doi}")
        except Exception as e:
            logger.error(f"Error caching paper data: {str(e)}", exc_info=True)

    async def get_paper(
        self, doi: str
    ) -> Tuple[Optional[str], Optional[str], Optional[Dict], Optional[io.BytesIO]]:
        """Attempt to retrieve paper from cache or Sci-Hub mirrors."""
        if not self.session:
            raise RuntimeError("Session not initialized. Call init() first.")

        # try to get from cache first
        if cached := await self.get_cached_paper(doi):
            logger.info(f"Retrieved paper from cache for DOI: {doi}")
            return cached

        logger.info(f"Attempting to retrieve paper with DOI: {doi}")
        metadata = await self.get_paper_metadata(doi)

        for domain in self.domains:
            logger.debug(f"Trying domain: {domain}")

            result = await self._make_request(domain, "Paper", doi)
            if not result:
                continue

            status, html = result
            if status == 200:
                if pdf_url := self.extract_pdf_url(html, domain):
                    logger.info(f"Successfully found PDF at {domain}")
                    preview = await self.get_pdf_preview(pdf_url)

                    # cache the results
                    await self.cache_paper(doi, pdf_url, domain, metadata, preview)

                    return pdf_url, domain, metadata, preview
                logger.warning(f"No PDF URL found in response from {domain}")

        logger.error(f"Failed to retrieve paper from all mirrors for DOI: {doi}")
        return None, None, None, None
