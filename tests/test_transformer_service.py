"""Transformer list paging is local. A bad capacity becomes null, not zero."""

import pytest

from app.cache import TtlCache
from app.errors import NotFoundError
from app.services.transformer_service import TransformerService
from tests.fakes import RecordingPortal
from tests.samples import transformer_record


def test_normalization_and_local_pagination():
    """Bad capacity is null. A row with no code is skipped. Page 2 still reports total 3."""

    portal = RecordingPortal(
        transformers=[
            transformer_record(),
            transformer_record(code="DT-002", name="DT 2", feederCode="F-002", capacityKva="many"),
            transformer_record(code="DT-003", capacityKva=250),
            {"name": "no code"},
        ]
    )
    service = TransformerService(portal, TtlCache(300))

    page = service.list_transformers(page=1, page_size=2)
    assert [item.code for item in page.data] == ["DT-001", "DT-002"]
    assert page.pagination.total == 3
    assert page.pagination.total_pages == 2
    assert page.data[0].capacity_kva == 100.0
    assert page.data[1].capacity_kva is None

    assert service.list_transformers(page=2, page_size=2).data[0].code == "DT-003"
    assert service.get_transformer("dt-003").capacity_kva == 250.0
    with pytest.raises(NotFoundError):
        service.get_transformer("DT-999")
    assert portal.transformer_calls == 1
