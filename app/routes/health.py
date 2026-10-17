from fastapi import APIRouter

router = APIRouter()

@router.get("/health")
def health() -> dict:
    """Report that the API is up.

    Returns a fixed JSON body. Docker, Cloud Run, and CI can call this to
    check the container started, without touching a database.
    """
    return {"status": "ok"}
