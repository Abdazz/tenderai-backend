"""Exponential-backoff retries for HTTP fetches.

We retry on transient failures only — TCP/connection errors, request
timeouts, and 5xx / 429 server responses. 4xx other than 429 are left as-is
because retrying them would just hammer the upstream with the same bad
request. Backoff is exponential with jitter so a flaky source doesn't
synchronise retries across our concurrent fetches.
"""

from __future__ import annotations

from typing import Any

import httpx
from tenacity import (
    AsyncRetrying,
    RetryError,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

from ..config import settings
from ..logging import get_logger

logger = get_logger(__name__)


# Status codes worth retrying. 429 = Too Many Requests, 5xx = upstream issues.
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(
        exc,
        (
            httpx.TimeoutException,
            httpx.ConnectError,
            httpx.ReadError,
            httpx.RemoteProtocolError,
        ),
    ):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in _RETRYABLE_STATUS
    return False


async def fetch_with_retry(
    client: httpx.AsyncClient,
    url: str,
    *,
    timeout: float = 30.0,
    max_attempts: int | None = None,
    label: str = "fetch",
    raise_for_status: bool = True,
    **request_kwargs: Any,
) -> httpx.Response:
    """GET ``url`` with exponential backoff on transient failures.

    Args:
        client: An open httpx.AsyncClient.
        url: Target URL.
        timeout: Per-request timeout passed to httpx.
        max_attempts: Total attempts (incl. the first try). Defaults to
            ``settings.fetch.max_retries`` when not supplied.
        label: Free-form tag included in log lines so callers can be
            distinguished in logs (e.g. ``"listing"`` vs ``"item"``).
        raise_for_status: When True, ``response.raise_for_status()`` is
            called inside the retry loop so 5xx/429 trigger backoff.
        **request_kwargs: Forwarded to ``client.get`` (e.g. params, headers).

    Returns:
        The successful httpx.Response (caller must read .text / .content /
        .json() as needed).

    Raises:
        The last exception encountered if all attempts fail.
    """
    attempts = (
        max_attempts if max_attempts is not None else max(1, settings.fetch.max_retries)
    )

    async for attempt in AsyncRetrying(
        retry=retry_if_exception(_is_retryable),
        wait=wait_exponential_jitter(initial=1.0, max=30.0, jitter=2.0),
        stop=stop_after_attempt(attempts),
        reraise=True,
    ):
        with attempt:
            n = attempt.retry_state.attempt_number
            if n > 1:
                logger.info(
                    "Retrying HTTP fetch",
                    label=label,
                    url=url,
                    attempt=n,
                    max_attempts=attempts,
                )
            response = await client.get(url, timeout=timeout, **request_kwargs)
            if raise_for_status:
                response.raise_for_status()
            return response

    # AsyncRetrying with reraise=True will have already raised if all
    # attempts failed; this line is unreachable but keeps mypy happy.
    raise RetryError(
        f"All {attempts} attempts to fetch {url} failed"
    )  # pragma: no cover


__all__ = ["fetch_with_retry"]
