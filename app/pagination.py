"""In-process pagination. Callers filter first; this function only slices.

A page past the end is an empty list with the original total, not an error.
`total_pages` is 0 when nothing matched.
"""

import math
from collections.abc import Sequence
from typing import TypeVar

from app.errors import InvalidQuery
from app.schemas import Pagination

T = TypeVar("T")


def paginate(items: Sequence[T], page: int, page_size: int) -> tuple[list[T], Pagination]:
    """Slice an already filtered list. A page past the end is empty and keeps the real total."""

    if page < 1 or page_size < 1:
        raise InvalidQuery("invalid_pagination", "page and page_size must be positive integers.")
    total = len(items)
    total_pages = math.ceil(total / page_size) if total else 0
    start = (page - 1) * page_size
    return list(items[start : start + page_size]), Pagination(
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )
