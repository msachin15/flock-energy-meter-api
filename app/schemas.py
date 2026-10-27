"""Public API models.

Portal fields stay in camelCase at the source and are mapped to snake_case here.
See PROTOCOL.md for the mapping and for which portal quirks are preserved.
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.constants import CONSUMPTION_INTERPRETATION, RECORDED_AT_CONVENTION


class ErrorBody(BaseModel):
    model_config = ConfigDict(frozen=True)

    error: str
    message: str
    details: list[dict[str, Any]] | None = None


class HealthResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["ok"]
    portal: Literal["not_checked"] = Field(
        description="Always not_checked. This endpoint does not call the portal."
    )


class Pagination(BaseModel):
    model_config = ConfigDict(frozen=True)

    total: int = Field(description="Number of records after filtering and before pagination.")
    page: int = Field(description="1-based page number that was requested.")
    page_size: int
    total_pages: int = Field(description="Zero when total is zero.")


class HierarchyNode(BaseModel):
    """One level of the network hierarchy.

    Empty strings are preserved. A missing level is null on NetworkHierarchy,
    which is different from a level that exists with a blank code or name.
    """

    model_config = ConfigDict(frozen=True)

    name: str | None = Field(default=None, description="Source field: name. Empty string is preserved.")
    code: str | None = Field(default=None, description="Source field: code. Empty string is preserved.")


class NetworkHierarchy(BaseModel):
    model_config = ConfigDict(frozen=True)

    zone: HierarchyNode | None = None
    circle: HierarchyNode | None = None
    division: HierarchyNode | None = None
    subdivision: HierarchyNode | None = None
    substation: HierarchyNode | None = None
    feeder: HierarchyNode | None = None
    dt: HierarchyNode | None = None


class Meter(BaseModel):
    """Meter metadata taken from the bulk export.

    Field mapping: meterId, serialNo, make, phaseType, installStatus,
    installType, build, dtCode, hierarchy, geo.lat, geo.lng.
    """

    model_config = ConfigDict(frozen=True)

    meter_id: str = Field(description="Source field: meterId.", examples=["J100000"])
    serial_no: str | None = Field(default=None, description="Source field: serialNo.")
    make: str | None = None
    phase_type: str | None = Field(default=None, description="Source field: phaseType.")
    install_status: str | None = Field(default=None, description="Source field: installStatus.")
    install_type: str | None = Field(
        default=None,
        description="Source field: installType. Present on the export, absent from the paged search list.",
    )
    build: str | None = Field(
        default=None,
        description="Source field: build. Present on the export, absent from the paged search list.",
    )
    dt_code: str | None = Field(
        default=None,
        description="Source field: dtCode. Matches a transformer code. Empty string is preserved.",
    )
    hierarchy: NetworkHierarchy
    latitude: float | None = Field(default=None, description="Source field: geo.lat, as a number.")
    longitude: float | None = Field(default=None, description="Source field: geo.lng, as a number.")


class MeterPage(BaseModel):
    model_config = ConfigDict(frozen=True)

    data: list[Meter]
    pagination: Pagination


class MeterLocation(BaseModel):
    model_config = ConfigDict(frozen=True)

    meter_id: str
    latitude: float
    longitude: float
    source: Literal["export", "geo_endpoint"] = Field(
        description="export when geo.lat and geo.lng were usable. geo_endpoint when the dedicated geography call was required."
    )


class ConsumptionReading(BaseModel):
    model_config = ConfigDict(frozen=True)

    recorded_at: str = Field(
        description="Naive portal-local datetime, YYYY-MM-DDTHH:mm:ss, with no offset.",
        examples=["2026-06-24T00:00:00"],
    )
    source_timestamp: str = Field(
        description="Original portal timestamp, DD/MM/YYYY HH:mm.",
        examples=["24/06/2026 00:00"],
    )
    kwh: float | None = Field(default=None, description="Null when missing or not a finite number. Never coerced to zero.")
    kvah: float | None = Field(default=None, description="Null when missing or not a finite number. Never coerced to zero.")
    volt_r: float | None = Field(
        default=None,
        description="Source field: voltR. Null when missing or not a finite number.",
    )


class RejectedReading(BaseModel):
    """A history row that could not be placed in time.

    These rows are listed so malformed data is not dropped without a trace.
    Date filters do not apply to them, because they have no usable timestamp.
    """

    model_config = ConfigDict(frozen=True)

    index: int = Field(description="Zero-based index in the upstream data array.")
    reason: Literal["invalid_timestamp", "not_an_object"]
    source_timestamp: str | None = None


class ConsumptionResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    meter_id: str
    timezone: Literal[None] = Field(
        default=None,
        description="Always null. The portal timestamp has no timezone.",
    )
    recorded_at_convention: str = RECORDED_AT_CONVENTION
    interpretation: str = CONSUMPTION_INTERPRETATION
    readings: list[ConsumptionReading]
    rejected: list[RejectedReading]


class Transformer(BaseModel):
    """Distribution transformer.

    Field mapping: code, name, feederCode, capacityKva.
    Meters reference this record through dt_code.
    """

    model_config = ConfigDict(frozen=True)

    code: str = Field(examples=["DT-001"])
    name: str | None = None
    feeder_code: str | None = Field(default=None, description="Source field: feederCode.")
    capacity_kva: float | None = Field(
        default=None,
        description="Source field: capacityKva. Null when missing or not a finite number.",
    )


class TransformerPage(BaseModel):
    model_config = ConfigDict(frozen=True)

    data: list[Transformer]
    pagination: Pagination
