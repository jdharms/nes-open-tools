"""What more than one of the route modules needs: outcomes, refusals and the download cookie."""

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, Response

from ..auth import current_user
from ..config import Config
from ..download_settings import load_settings
from ..forms import SavedSettings

#: a player's saved download settings (`SavedSettings.to_cookie`), set by each download
DOWNLOAD_COOKIE = "golf_download"
#: seconds the saved download settings last from each download
DOWNLOAD_COOKIE_MAX_AGE = 365 * 24 * 60 * 60


def outcome(request: Request, reason: str) -> None:
    """What a request came to, beyond its status code, for its timing row."""
    request.state.sample.outcome = reason


def not_found() -> HTTPException:
    return HTTPException(status_code=404)


def json_refusal(
    status_code: int, reason: str, values: dict | None = None
) -> JSONResponse:
    """A download refusal: download.js shows the notice for `error`, filled from `values`."""
    return JSONResponse(
        {"error": reason, "values": values or {}}, status_code=status_code
    )


def saved_settings(request: Request) -> SavedSettings:
    """A player's saved settings: the account's when signed in and saved, else the cookie's."""
    user = current_user(request)
    if user is not None:
        account = load_settings(request.app.state.db, user.id)
        if account is not None:
            return account
    return SavedSettings.from_cookie(request.cookies.get(DOWNLOAD_COOKIE))


def set_download_cookie(
    request: Request, response: Response, saved: SavedSettings
) -> None:
    config: Config = request.app.state.config
    response.set_cookie(
        DOWNLOAD_COOKIE,
        saved.to_cookie(),
        max_age=DOWNLOAD_COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=config.base_url.startswith("https://"),
    )


def delete_download_cookie(request: Request, response: Response) -> None:
    config: Config = request.app.state.config
    response.delete_cookie(
        DOWNLOAD_COOKIE,
        httponly=True,
        samesite="lax",
        secure=config.base_url.startswith("https://"),
    )
