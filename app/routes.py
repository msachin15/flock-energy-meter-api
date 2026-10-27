"""HTTP routes. Every route is read-only."""

from datetime import date

from fastapi import APIRouter, Depends, Query, Request

from app.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.schemas import (
    ConsumptionResponse,
    ErrorBody,
    HealthResponse,
    Meter,
    MeterLocation,
    MeterPage,
    Transformer,
    TransformerPage,
)
from app.services.meter_service import MeterService
from app.services.transformer_service import TransformerService

router = APIRouter()
api = APIRouter(prefix="/api/v1")

_ERROR_RESPONSES = {
    404: {"model": ErrorBody, "description": "The meter or transformer does not exist, or coordinates are unavailable."},
    422: {"model": ErrorBody, "description": "A query parameter is invalid."},
    502: {"model": ErrorBody, "description": "The portal could not be authenticated to, reached, or understood."},
    504: {"model": ErrorBody, "description": "The portal timed out."},
}


def get_meter_service(request: Request) -> MeterService:
    """The meter service stored on the app at startup."""

    return request.app.state.meter_service


def get_transformer_service(request: Request) -> TransformerService:
    """The transformer service stored on the app at startup."""

    return request.app.state.transformer_service


@router.get(
    "/health",
    response_model=HealthResponse,
    operation_id="getHealth",
    summary="Application health",
    tags=["health"],
    description=(
        "Reports that this process is running. It does not call the Urja Meter Ops portal, "
        "so a successful response does not mean the portal is healthy."
    ),
)
def health() -> HealthResponse:
    """Process is up. This does not call the portal."""

    return HealthResponse(status="ok", portal="not_checked")


@api.get(
    "/meters",
    response_model=MeterPage,
    operation_id="listMeters",
    summary="List and search meters",
    tags=["meters"],
    responses=_ERROR_RESPONSES,
    description=(
        "Returns meter metadata from the signed bulk export. "
        "The optional query is a case-insensitive substring of the meter id or serial number. "
        "Filtering happens before pagination, so pagination.total is the filtered count. "
        "Order follows the export. A page past the end returns an empty data array and the real total."
    ),
)
def list_meters(
    query: str | None = Query(
        default=None,
        description="Case-insensitive substring matched against meter id or serial number.",
    ),
    page: int = Query(default=1, ge=1, description="1-based page number."),
    page_size: int = Query(
        default=DEFAULT_PAGE_SIZE,
        ge=1,
        le=MAX_PAGE_SIZE,
        description=f"Page size. Maximum {MAX_PAGE_SIZE}.",
    ),
    service: MeterService = Depends(get_meter_service),
) -> MeterPage:
    """Search and page the cached meter export."""

    return service.list_meters(query, page, page_size)


@api.get(
    "/meters/{meter_id}",
    response_model=Meter,
    operation_id="getMeter",
    summary="Retrieve one meter",
    tags=["meters"],
    responses=_ERROR_RESPONSES,
    description=(
        "Returns the export record for one meter, including installation type, build, "
        "network hierarchy, and numeric coordinates when the export has them. "
        "Lookup is exact, then case-insensitive."
    ),
)
def get_meter(meter_id: str, service: MeterService = Depends(get_meter_service)) -> Meter:
    """One meter, or 404."""

    return service.get_meter(meter_id)


@api.get(
    "/meters/{meter_id}/location",
    response_model=MeterLocation,
    operation_id="getMeterLocation",
    summary="Meter coordinates",
    tags=["meters"],
    responses=_ERROR_RESPONSES,
    description=(
        "Returns numeric latitude and longitude. The export geo object is used when both "
        "values are finite numbers. The geography endpoint is called only when they are not. "
        "Unknown meters use error not_found. A known meter with no usable coordinates uses "
        "error location_unavailable. Both are HTTP 404."
    ),
)
def get_meter_location(meter_id: str, service: MeterService = Depends(get_meter_service)) -> MeterLocation:
    """Numeric coordinates. 404 if the meter or the point is missing."""

    return service.get_location(meter_id)


@api.get(
    "/meters/{meter_id}/consumption",
    response_model=ConsumptionResponse,
    operation_id="getMeterConsumption",
    summary="Consumption history",
    tags=["meters"],
    responses=_ERROR_RESPONSES,
    description=(
        "Returns normalized register readings for one meter, in chronological order. "
        "start_date and end_date are inclusive calendar dates in YYYY-MM-DD and are compared "
        "with the date portion of the naive recorded_at value. "
        "An end date before the start date is HTTP 422. "
        "Readings with an unusable timestamp are returned in rejected and are not turned into zeroes. "
        "History is not cached."
    ),
)
def get_meter_consumption(
    meter_id: str,
    start_date: date | None = Query(
        default=None,
        description="Inclusive start date, YYYY-MM-DD, compared with the naive recorded_at calendar date.",
    ),
    end_date: date | None = Query(
        default=None,
        description="Inclusive end date, YYYY-MM-DD.",
    ),
    service: MeterService = Depends(get_meter_service),
) -> ConsumptionResponse:
    """History for one meter. Dates are optional and inclusive."""

    return service.get_consumption(meter_id, start_date, end_date)


@api.get(
    "/transformers",
    response_model=TransformerPage,
    operation_id="listTransformers",
    summary="List transformers",
    tags=["transformers"],
    responses=_ERROR_RESPONSES,
    description=(
        "Returns distribution transformers. Upstream pages are read until the reported total "
        "is reached, then cached. This endpoint paginates that cached list and does not "
        "repeat the upstream walk on every call."
    ),
)
def list_transformers(
    page: int = Query(default=1, ge=1, description="1-based page number."),
    page_size: int = Query(
        default=DEFAULT_PAGE_SIZE,
        ge=1,
        le=MAX_PAGE_SIZE,
        description=f"Page size. Maximum {MAX_PAGE_SIZE}.",
    ),
    service: TransformerService = Depends(get_transformer_service),
) -> TransformerPage:
    """Page the cached transformer list."""

    return service.list_transformers(page, page_size)


@api.get(
    "/transformers/{code}",
    response_model=Transformer,
    operation_id="getTransformer",
    summary="Retrieve one transformer",
    tags=["transformers"],
    responses=_ERROR_RESPONSES,
    description=(
        "Returns one transformer from the cached listing. No separate detail endpoint was observed. "
        "Lookup is exact, then case-insensitive."
    ),
)
def get_transformer(code: str, service: TransformerService = Depends(get_transformer_service)) -> Transformer:
    """One transformer, or 404."""

    return service.get_transformer(code)
