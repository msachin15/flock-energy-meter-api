"""FastAPI application factory."""

import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.cache import TtlCache
from app.config import Settings, get_settings
from app.constants import API_TITLE, API_VERSION
from app.errors import (
    AuthenticationError,
    InvalidQuery,
    NotFoundError,
    PortalConnectionError,
    PortalDataError,
    PortalTimeoutError,
    PortalUpstreamError,
    error_payload,
)
from app.logging_config import configure_logging
from app.portal_client import PortalClient
from app.routes import api, router
from app.services.meter_service import MeterService
from app.services.transformer_service import TransformerService

logger = logging.getLogger("flock_energy.api")

_PUBLIC_DESCRIPTION = """
Read-only API in front of the Urja Meter Ops portal.

Meter metadata comes from the signed bulk export. Consumption history is requested
per meter and is not cached. Timestamps are naive portal-local datetimes: the
service does not add a timezone or UTC marker.

This process authenticates to the portal with credentials from the environment.
Callers of this API do not send those credentials. There are no write endpoints.
""".strip()


def create_app(settings: Settings | None = None, portal: Any | None = None) -> FastAPI:
    """Build the app, the portal client, and two separate caches. Tests pass a fake portal."""

    configure_logging()
    active_settings = settings or get_settings()
    portal_client = portal if portal is not None else PortalClient(active_settings)
    meter_service = MeterService(portal_client, TtlCache(active_settings.cache_ttl_seconds))
    transformer_service = TransformerService(portal_client, TtlCache(active_settings.cache_ttl_seconds))

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        """Close the portal session when the process stops."""

        yield
        closer = getattr(portal_client, "close", None)
        if closer is not None:
            closer()

    application = FastAPI(
        title=API_TITLE,
        version=API_VERSION,
        description=_PUBLIC_DESCRIPTION,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )
    application.state.settings = active_settings
    application.state.portal = portal_client
    application.state.meter_service = meter_service
    application.state.transformer_service = transformer_service
    application.include_router(router)
    application.include_router(api)
    _register_handlers(application)
    return application


def _register_handlers(application: FastAPI) -> None:
    """Map typed failures to HTTP responses. Clients never receive a traceback."""

    @application.exception_handler(NotFoundError)
    async def not_found(_request: Request, exc: NotFoundError) -> JSONResponse:
        """404 for a missing meter, transformer, or consumption series."""

        return JSONResponse(status_code=404, content=error_payload(exc.error, exc.message))

    @application.exception_handler(InvalidQuery)
    async def invalid_query(_request: Request, exc: InvalidQuery) -> JSONResponse:
        """422 when end_date is before start_date, or page size exceeds the cap."""

        return JSONResponse(status_code=422, content=error_payload(exc.error, exc.message))

    @application.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
        """422 for a malformed query. Field values are included only when they are plain scalars."""

        details = []
        for item in exc.errors():
            detail: dict[str, Any] = {
                "loc": [str(part) for part in item.get("loc", ())],
                "msg": str(item.get("msg", "Invalid value")),
                "type": str(item.get("type", "value_error")),
            }
            incoming = item.get("input")
            if isinstance(incoming, (str, int, float, bool)) or incoming is None:
                detail["input"] = incoming
            details.append(detail)
        return JSONResponse(
            status_code=422,
            content=error_payload("validation_error", "Request parameters are invalid.", details),
        )

    @application.exception_handler(AuthenticationError)
    async def authentication_failed(request: Request, exc: AuthenticationError) -> JSONResponse:
        """502. This API has no caller login, so a portal login failure is not a 401."""

        # 502, not 401: this API has no caller login. The failure is ours, against the portal.
        logger.error("Portal authentication failed path=%s", request.url.path)
        return JSONResponse(
            status_code=502,
            content=error_payload(
                "authentication_failed",
                "The service could not authenticate to the upstream portal.",
            ),
        )

    @application.exception_handler(PortalTimeoutError)
    async def upstream_timeout(request: Request, _exc: PortalTimeoutError) -> JSONResponse:
        """504 when the portal exceeds PORTAL_TIMEOUT_SECONDS."""

        logger.error("Portal timeout path=%s", request.url.path)
        return JSONResponse(
            status_code=504,
            content=error_payload("upstream_timeout", "The upstream portal timed out."),
        )

    @application.exception_handler(PortalConnectionError)
    async def upstream_down(request: Request, _exc: PortalConnectionError) -> JSONResponse:
        """502 when the portal host cannot be reached."""

        logger.error("Portal unreachable path=%s", request.url.path)
        return JSONResponse(
            status_code=502,
            content=error_payload("upstream_unavailable", "The upstream portal could not be reached."),
        )

    @application.exception_handler(PortalUpstreamError)
    async def upstream_status(request: Request, exc: PortalUpstreamError) -> JSONResponse:
        """502 when the portal returns an HTTP error. The portal path stays in the log only."""

        logger.error(
            "Portal status=%s portal_path=%s api_path=%s",
            exc.status_code,
            exc.path,
            request.url.path,
        )
        return JSONResponse(
            status_code=502,
            content=error_payload("upstream_error", "The upstream portal returned an error."),
        )

    @application.exception_handler(PortalDataError)
    async def upstream_data(request: Request, _exc: PortalDataError) -> JSONResponse:
        """502 when the body is not the JSON shape this client expects."""

        logger.error("Portal data was unusable path=%s", request.url.path)
        return JSONResponse(
            status_code=502,
            content=error_payload(
                "upstream_data",
                "The upstream portal returned a response that could not be used.",
            ),
        )

    @application.exception_handler(StarletteHTTPException)
    async def http_exception(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
        """404 and 405 for paths and methods this API does not offer."""

        if exc.status_code == 404:
            return JSONResponse(
                status_code=404,
                content=error_payload("not_found", "The requested resource was not found."),
            )
        if exc.status_code == 405:
            return JSONResponse(
                status_code=405,
                content=error_payload("method_not_allowed", "That method is not supported on this path."),
            )
        return JSONResponse(
            status_code=exc.status_code,
            content=error_payload("http_error", "The request could not be completed."),
        )

    @application.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception) -> JSONResponse:
        """500 with a generic message. The traceback is logged, not returned."""

        logger.exception("Unhandled error path=%s error_type=%s", request.url.path, type(exc).__name__)
        return JSONResponse(
            status_code=500,
            content=error_payload("internal_error", "The request could not be completed."),
        )


app = create_app()
