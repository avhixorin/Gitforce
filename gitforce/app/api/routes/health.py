from fastapi import APIRouter

from gitforce.app.api.schemas import HealthOut

router = APIRouter(tags=["health"])

VERSION = "0.1.0"


@router.get("/health", response_model=HealthOut)
async def health() -> HealthOut:
    return HealthOut(status="ok", version=VERSION)