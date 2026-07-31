from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

from app.dependencies import get_link_service
from app.models import ShortenRequest, ShortenResponse
from app.services.link_service import LinkService

router = APIRouter()


@router.post("/shorten", response_model=ShortenResponse)
async def shorten(
    body: ShortenRequest,
    service: LinkService = Depends(get_link_service),
):
    return await service.shorten(body)


@router.get("/s/{short_id}")
async def redirect(
    short_id: str,
    service: LinkService = Depends(get_link_service),
):
    original_url = await service.get_original_url(short_id)
    if original_url is None:
        raise HTTPException(status_code=404, detail="Link not found")
    return RedirectResponse(url=original_url, status_code=302)


@router.get("/")
async def index():
    with open("static/index.html") as f:
        return HTMLResponse(content=f.read())
