"""The FastAPI application: the pages, the API and the state they share."""

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from coderagent.config.loader import load_config
from coderagent.config.schema import Config
from coderagent.core.protocols import ModelBackend
from coderagent.core.session import SessionStore
from coderagent.web.api import router
from coderagent.web.sessions import SessionRegistry

TEMPLATES = Path(__file__).parent / "templates"


def create_app(
    config: Config,
    cwd: Path,
    *,
    store: SessionStore | None = None,
    model: ModelBackend | None = None,
    config_spec: list[str] | None = None,
    permission_mode: str | None = None,
) -> FastAPI:
    """The web interface of the coding agent.

    `config` is the configuration the server started with. A new session reads
    the configuration files again, so what the user writes in the settings page
    is picked up by the sessions that come after it.
    """
    cwd = Path(cwd)
    spec = list(config_spec or [])
    registry = SessionRegistry(config, cwd, store=store, model=model, permission_mode=permission_mode, config_spec=spec)
    app = FastAPI(title="coderagent", docs_url="/api/docs")
    app.state.registry = registry
    app.state.cwd = cwd
    app.state.config = config
    app.state.config_spec = spec
    app.state.config_of = lambda: load_config(app.state.config_spec, cwd=cwd)
    app.include_router(router)

    templates = Jinja2Templates(directory=str(TEMPLATES))
    app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")

    @app.get("/")
    def chat(request: Request):
        """The chat page."""
        return templates.TemplateResponse(request, "chat.html", {"cwd": str(cwd)})

    @app.get("/settings")
    def settings(request: Request):
        """The page where the model is configured."""
        return templates.TemplateResponse(request, "settings.html", {"cwd": str(cwd)})

    return app
