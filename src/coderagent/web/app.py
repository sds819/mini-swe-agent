"""The FastAPI application: the pages, the API and the state they share."""

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from coderagent.config.loader import load_config
from coderagent.config.schema import Config
from coderagent.core.protocols import ModelBackend
from coderagent.core.session import SessionStore
from coderagent.web.api import router
from coderagent.web.i18n import COOKIE, DEFAULT_LANGUAGE, LANGUAGES, STRINGS, Language, locale_of
from coderagent.web.sessions import SessionRegistry

TEMPLATES = Path(__file__).parent / "templates"


def available_languages() -> tuple[Language, ...]:
    """The languages that can be served: templates and strings are both there."""
    return tuple(
        language for language in LANGUAGES if (TEMPLATES / language.code).is_dir() and language.code in STRINGS
    )


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

    languages = available_languages()
    codes = [language.code for language in languages]
    templates = {language.code: Jinja2Templates(directory=str(TEMPLATES / language.code)) for language in languages}
    app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")

    def page(request: Request, name: str) -> Any:
        """A page in the language of the visitor."""
        language = locale_of(request, codes)
        return templates[language].TemplateResponse(
            request,
            name,
            {
                "cwd": str(cwd),
                "language": language,
                "languages": languages,
                "strings": STRINGS[language],
            },
        )

    @app.get("/")
    def chat(request: Request):
        """The chat page."""
        return page(request, "chat.html")

    @app.get("/settings")
    def settings(request: Request):
        """The page where the model is configured."""
        return page(request, "settings.html")

    @app.get("/api/i18n/{language}")
    def strings_of(language: str):
        """The strings of a language, for a browser that switches without a reload."""
        if language not in codes:
            raise HTTPException(status_code=404, detail="unknown language")
        return {"language": language, "strings": STRINGS[language]}

    @app.get("/lang/{language}")
    def set_language(language: str, request: Request):
        """The language the visitor chose, remembered in a cookie."""
        if language not in codes:
            language = DEFAULT_LANGUAGE if DEFAULT_LANGUAGE in codes else codes[0]
        target = request.query_params.get("next", "/")
        if not target.startswith("/") or target.startswith("//"):
            target = "/"
        response = RedirectResponse(target, status_code=303)
        response.set_cookie(COOKIE, language, max_age=31536000, samesite="lax")
        return response

    return app
