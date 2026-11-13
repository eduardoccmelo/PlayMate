import logging

from fastapi import APIRouter

from app.api.deps import SessionDep, ViewerDep
from app.core.config import get_settings
from app.domain import auth as auth_domain
from app.domain.errors import ServiceUnavailable
from app.services.mailer import Mailer
from app.schemas.auth import (
    AccessCodeResponse,
    SessionResponse,
    StartSignInRequest,
    StartSignInResponse,
    UpdateMeRequest,
    UserResponse,
    VerifyRequest,
)

router = APIRouter(tags=["auth"])
logger = logging.getLogger(__name__)


@router.post("/auth/start", response_model=StartSignInResponse)
async def start_sign_in(body: StartSignInRequest, session: SessionDep) -> StartSignInResponse:
    settings = get_settings()
    if not settings.exposes_access_codes and not settings.has_smtp:
        raise ServiceUnavailable("Email delivery is not configured")
    issued = await auth_domain.start_sign_in(
        session, email=str(body.email), display_name=body.display_name
    )
    # Commit before delivery: a received code must always correspond to a
    # durable hash. If delivery fails, the user can request a new code.
    await session.commit()
    if not settings.exposes_access_codes:
        await Mailer(settings).send_access_code(
            recipient=str(issued.user.email), code=issued.access_code
        )
    logger.info("Access code issued for %s", issued.user.email)
    return StartSignInResponse(
        sent=True,
        access_code=issued.access_code if settings.exposes_access_codes else None,
    )


@router.post("/auth/verify", response_model=SessionResponse)
async def verify(body: VerifyRequest, session: SessionDep) -> SessionResponse:
    issued = await auth_domain.verify_access_code(
        session,
        email=str(body.email),
        access_code=body.access_code,
        device_label=body.device_label,
    )
    return SessionResponse(
        token=issued.token, user=UserResponse.model_validate(issued.user)
    )


@router.get("/me", response_model=UserResponse)
async def read_me(viewer: ViewerDep) -> UserResponse:
    return UserResponse.model_validate(viewer.user)


@router.patch("/me", response_model=UserResponse)
async def update_me(body: UpdateMeRequest, viewer: ViewerDep) -> UserResponse:
    viewer.user.display_name = body.display_name
    return UserResponse.model_validate(viewer.user)


@router.post("/me/access-code/regenerate", response_model=AccessCodeResponse)
async def regenerate_access_code(session: SessionDep, viewer: ViewerDep) -> AccessCodeResponse:
    settings = get_settings()
    if not settings.exposes_access_codes and not settings.has_smtp:
        raise ServiceUnavailable("Email delivery is not configured")
    code = await auth_domain.regenerate_access_code(session, user_id=viewer.user.id)
    await session.commit()
    if not settings.exposes_access_codes:
        await Mailer(settings).send_access_code(recipient=str(viewer.user.email), code=code)
    return AccessCodeResponse(
        sent=True,
        access_code=code if settings.exposes_access_codes else None,
    )


@router.delete("/sessions/current", status_code=204)
async def sign_out(session: SessionDep, viewer: ViewerDep) -> None:
    await auth_domain.revoke_session(session, user_session=viewer.session)
