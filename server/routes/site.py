"""The pages that stand alone: home, ROM setup, the rangefinder, the Markdown pages, and
the health check."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from golf.randomizer.roms import VANILLA_ROMS
from golf.rendering.rangefinder import METADATA

from ..pages import ContentPage, PageCatalog
from ..strings import Strings

#: the catalog prefix whose strings the ROM setup page embeds for rom.js
ROM_SCRIPT_STRINGS = "rom.status"
#: the catalog prefix whose strings the rangefinder page embeds for its modules
RANGEFINDER_SCRIPT_STRINGS = "rangefinder.script"
#: where the rangefinder's renders (`Config.rangefinder_dir`) are served
RANGEFINDER_DATA_URL = "/rangefinder-data"


def site_router(templates: Jinja2Templates, pages: PageCatalog) -> APIRouter:
    router = APIRouter()

    @router.get("/", response_class=HTMLResponse)
    def home(request: Request):
        return templates.TemplateResponse(request, "home.html", {"page": "home"})

    def content_page(content: ContentPage):
        def show(request: Request):
            return templates.TemplateResponse(
                request,
                "page.html",
                {"page": "content", "content_page": content},
            )

        return show

    # A route per page rather than one `/pages/{slug}`, so each page's timings are its
    # own; a slug that names no enabled page matches nothing and is not found.
    for content in pages.enabled:
        router.add_api_route(
            f"/pages/{content.slug}",
            content_page(content),
            response_class=HTMLResponse,
            name=f"content_page_{content.slug}",
        )

    @router.get("/rom", response_class=HTMLResponse)
    def rom_setup(request: Request):
        strings: Strings = request.app.state.strings
        return templates.TemplateResponse(
            request,
            "rom.html",
            {
                "page": "rom",
                "roms": VANILLA_ROMS,
                "rom_strings": strings.for_script(ROM_SCRIPT_STRINGS),
            },
        )

    @router.get("/rangefinder", response_class=HTMLResponse)
    def rangefinder(request: Request):
        strings: Strings = request.app.state.strings
        return templates.TemplateResponse(
            request,
            "rangefinder.html",
            {
                "page": "rangefinder",
                "metadata_url": f"{RANGEFINDER_DATA_URL}/{METADATA}",
                "rangefinder_strings": strings.for_script(RANGEFINDER_SCRIPT_STRINGS),
            },
        )

    # UptimeRobot's free plan checks with HEAD, which a GET route would refuse with a 405.
    @router.api_route("/healthz", methods=["GET", "HEAD"])
    def healthz(request: Request) -> dict[str, str]:
        with request.app.state.db.transaction() as conn:
            conn.execute("SELECT 1").fetchone()
        return {"status": "ok"}

    return router
