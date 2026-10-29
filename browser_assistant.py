"""Operator-attended browser form assistant.

The module uses the official Playwright API with normal browser contexts.  It
intentionally excludes stealth, CAPTCHA handling, verification-code entry,
credential harvesting, payment entry, and final form submission.  Each job is
limited to an operator-approved target host and pauses for a human-controlled
approval flow before any consequential action.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from urllib.parse import urlparse

from playwright.async_api import Browser, Error as PlaywrightError, async_playwright


class BrowserPolicyError(PermissionError):
    """Raised when a request falls outside the attended-browser policy."""


@dataclass(frozen=True)
class BrowserPreparationResult:
    page_title: str
    origin: str
    fields_filled: int
    requires_human_approval: bool
    blocked_reason: str | None = None


class AttendedBrowserAssistant:
    """Prepare, but never submit, a form on an explicitly allowed target host."""

    _STOP_WORDS = ("captcha", "verification code", "two-factor", "2fa", "payment", "credit card")
    _SENSITIVE_SELECTORS = ("password", "passcode", "otp", "verification", "card", "cvv", "ssn")

    def __init__(self, *, allow_targets: set[str], job_timeout_seconds: float = 120.0) -> None:
        self.allow_targets = {host.lower() for host in allow_targets}
        self.job_timeout_seconds = job_timeout_seconds

    async def prepare_form(self, *, url: str, fields: dict[str, str]) -> BrowserPreparationResult:
        """Navigate and fill non-sensitive user-provided fields, then always pause."""
        host = (urlparse(url).hostname or "").lower()
        if not host or host not in self.allow_targets:
            raise BrowserPolicyError("Browser target is not in the operator-approved allow list.")
        self._validate_fields(fields)
        try:
            return await asyncio.wait_for(self._prepare_once(url, fields), timeout=self.job_timeout_seconds)
        except asyncio.TimeoutError as error:
            raise BrowserPolicyError("Browser preparation exceeded its bounded job timeout.") from error

    async def _prepare_once(self, url: str, fields: dict[str, str]) -> BrowserPreparationResult:
        last_error: PlaywrightError | None = None
        for attempt in range(1, 3):
            try:
                async with async_playwright() as playwright:
                    browser: Browser = await playwright.chromium.launch(headless=False)
                    context = await browser.new_context()
                    page = await context.new_page()
                    await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                    text = (await page.locator("body").inner_text())[:20_000].lower()
                    if any(word in text for word in self._STOP_WORDS):
                        return BrowserPreparationResult(
                            page_title=await page.title(),
                            origin=f"{urlparse(url).scheme}://{urlparse(url).netloc}",
                            fields_filled=0,
                            requires_human_approval=True,
                            blocked_reason="verification_or_sensitive_step_detected",
                        )
                    for selector, value in fields.items():
                        await page.locator(selector).fill(value, timeout=10_000)
                    return BrowserPreparationResult(
                        page_title=await page.title(),
                        origin=f"{urlparse(url).scheme}://{urlparse(url).netloc}",
                        fields_filled=len(fields),
                        requires_human_approval=True,
                    )
            except PlaywrightError as error:
                last_error = error
                if attempt < 2:
                    await asyncio.sleep(0.5 * attempt)
            finally:
                if "browser" in locals() and browser.is_connected():
                    await browser.close()
        raise BrowserPolicyError("Browser could not prepare the approved form.") from last_error

    def _validate_fields(self, fields: dict[str, str]) -> None:
        if not fields:
            raise BrowserPolicyError("At least one user-provided, non-sensitive field is required.")
        for selector, value in fields.items():
            lowered = selector.lower()
            if any(marker in lowered for marker in self._SENSITIVE_SELECTORS):
                raise BrowserPolicyError("Password, OTP, payment, and identity fields must be entered by the operator.")
            if len(value) > 500:
                raise BrowserPolicyError("A field value exceeds the attended-browser policy limit.")
