"""Transformer queries. Upstream pages are merged once and cached."""

from __future__ import annotations

import logging

from app.cache import TtlCache
from app.constants import MAX_PAGE_SIZE
from app.errors import InvalidQuery, NotFoundError, PortalDataError, safe_identifier
from app.normalize import find_transformer, normalize_transformer
from app.pagination import paginate
from app.portal_client import PortalClient
from app.schemas import Transformer, TransformerPage

logger = logging.getLogger("flock_energy.transformers")


class TransformerService:
    def __init__(self, portal: PortalClient, cache: TtlCache) -> None:
        """Hold the portal client and the transformer cache."""

        self._portal = portal
        self._cache = cache

    def list_transformers(self, page: int, page_size: int) -> TransformerPage:
        """Page the cached full list. Upstream page size and this page size are unrelated."""

        _check_page(page, page_size)
        rows, pagination = paginate(self._transformers(), page, page_size)
        return TransformerPage(data=[row.model_copy(deep=True) for row in rows], pagination=pagination)

    def get_transformer(self, code: str) -> Transformer:
        """Look up one code. The returned copy is not the cached object."""

        found = find_transformer(self._transformers(), code)
        if found is None:
            raise NotFoundError(
                "not_found",
                f"Transformer '{safe_identifier(code)}' was not found.",
            )
        return found.model_copy(deep=True)

    def _transformers(self) -> list[Transformer]:
        """Cached full transformer list."""

        return self._cache.get_or_load(self._load)

    def _load(self) -> list[Transformer]:
        """Normalize every upstream row. Skip blank codes and duplicates."""

        raw_records = self._portal.fetch_transformers()
        items: list[Transformer] = []
        seen: set[str] = set()
        skipped = 0
        duplicates = 0
        for record in raw_records:
            item = normalize_transformer(record)
            if item is None:
                skipped += 1
                continue
            key = item.code.casefold()
            if key in seen:
                duplicates += 1
                continue
            seen.add(key)
            items.append(item)
        if skipped:
            logger.warning("Skipped %s transformer records without a usable code", skipped)
        if duplicates:
            logger.warning("Skipped %s duplicate transformer codes", duplicates)
        if raw_records and not items:
            raise PortalDataError("Transformer listing contained no usable records.")
        return items


def _check_page(page: int, page_size: int) -> None:
    """Reject a non-positive page or a page size above the documented maximum."""

    if page < 1 or page_size < 1:
        raise InvalidQuery("invalid_pagination", "page and page_size must be positive integers.")
    if page_size > MAX_PAGE_SIZE:
        raise InvalidQuery("invalid_pagination", f"page_size cannot exceed {MAX_PAGE_SIZE}.")
