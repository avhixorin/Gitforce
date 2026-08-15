from fastapi import APIRouter

from gitforce.app.security.secrets import SecretManager

router = APIRouter(prefix="/api/security", tags=["security"])


@router.get("/secrets")
async def list_secrets() -> dict[str, object]:
    """Return masked descriptors for registered secrets.

    Values are never returned — only whether each secret is configured
    (and its redaction pattern is active).
    """
    manager = SecretManager()
    described = manager.describe()
    return {"secrets": described}
