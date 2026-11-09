"""The language of the pages: Chinese for a Chinese region, English everywhere else.

The region of the visitor comes from the proxy in front of the server, or from
a geoip database. The visitor can always say which language they want: with
`?lang=zh` or with the box in the top bar, which remembers it in a cookie.

A language is added in three places: its templates in `templates/<code>/`, its
strings in `STRINGS` and its entry in `LANGUAGES`. A language that has no
templates is not offered.
"""

import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from coderagent.paths import config_home


@dataclass(frozen=True)
class Language:
    """A language of the pages."""

    code: str
    """The code of the language: `en`, `zh`."""

    name: str
    """The name of the language in that language: `English`, `中文`."""

    english: str
    """The name of the language in English: `English`, `Chinese`."""


LANGUAGES: tuple[Language, ...] = (
    Language("en", "English", "English"),
    Language("zh", "中文", "Chinese"),
)
"""The languages of the pages. One is only offered when its templates are there."""

REGION_LANGUAGES = {
    "CN": "zh",
    "HK": "zh",
    "MO": "zh",
    "TW": "zh",
    "JP": "ja",
    "FR": "fr",
    "DE": "de",
}
"""The language of a region. A region whose language is not offered falls back to the browser."""

COUNTRY_HEADERS = ("CF-IPCountry", "X-AppEngine-Country", "X-Vercel-IP-Country", "X-Country-Code")
"""The headers a proxy in front of the server sets the country in."""

UNKNOWN_COUNTRIES = ("XX", "T1", "")
"""The values a proxy puts there when it does not know the country."""

GEOIP_ENV = "CODERAGENT_GEOIP_DB"
"""Where the geoip database is, if it is not in the config home."""

COOKIE = "coder_lang"
"""The cookie that holds the language the visitor chose."""

DEFAULT_LANGUAGE = "en"
"""The language of the pages when nothing else says which one."""

STRINGS: dict[str, dict[str, str]] = {
    "en": {
        "history": "earlier turns",
        "earlier_turns": "{count} earlier turns",
        "tool": "tool",
        "running": "running…",
        "approval": "approval: {tool}",
        "allow": "Allow",
        "deny": "Deny",
        "always": "Always allow",
        "answered": "answered…",
        "error": "error: {message}",
        "no_answer": "no answer: denied",
        "answered_decision": "answered: {decision}",
        "compacted": "the context was compacted ({tokens} tokens)",
        "settled": "the session was settled in the memory (${cost})",
        "rolled_back": "the conversation was rolled back to {messages} messages",
        "mode_default": "Every tool that changes something asks for approval.",
        "mode_acceptEdits": "The writes go through, everything else asks for approval.",
        "mode_plan": "Read only: the agent looks around and writes down the plan.",
        "mode_readonly": "Read only: the agent looks around and answers.",
        "mode_bypass": "Nothing is asked: every tool call is allowed. For unattended runs.",
        "from": "from: {source}",
        "server_mode": "The server was started with --permission-mode {mode}: the mode of the file does not decide anything.",
        "trying": "trying…",
        "ok_ms": "ok: {ms}ms",
        "saved": "saved to {path}",
        "no_key": "no key is set",
        "not_set": "not set",
        "not_an_alias": "the model is not an alias of this file, it is called as it is",
        "tools_ok": "ok, the model calls the tools",
        "tools_failed": "the model did not call the tool",
        "not_tried": "not tried",
        "row_model": "model",
        "row_api_base": "api base",
        "row_api_key": "api key",
        "row_aliases": "aliases file",
        "row_tools": "tools",
        "key_set": "set ({hint}) — click to show it",
        "key_not_set": "not set — click to show it",
        "key_of_endpoint": "the key of the endpoint",
        "field_session_id": "session id",
        "field_model": "model",
        "field_tokens": "tokens",
        "field_window": "window",
        "field_cost": "cost",
        "field_cwd": "directory",
        "field_mode": "mode",
        "field_state": "state",
        "field_sandbox": "sandbox",
        "field_busy": "busy",
    },
    "zh": {
        "history": "之前的几轮",
        "earlier_turns": "之前的 {count} 轮",
        "tool": "工具",
        "running": "运行中…",
        "approval": "审批：{tool}",
        "allow": "允许",
        "deny": "拒绝",
        "always": "始终允许",
        "answered": "已回答…",
        "error": "错误：{message}",
        "no_answer": "没有回答：已拒绝",
        "answered_decision": "已回答：{decision}",
        "compacted": "上下文已压缩（{tokens} tokens）",
        "settled": "会话已写入记忆（${cost}）",
        "rolled_back": "对话已回滚到 {messages} 条消息",
        "mode_default": "凡是会改东西的工具都要审批。",
        "mode_acceptEdits": "写操作直接放行，其余的还是要问。",
        "mode_plan": "只读：agent 只看不改，把计划写出来。",
        "mode_readonly": "只读：agent 只看不改，把看到的说出来。",
        "mode_bypass": "一律不问，所有工具调用都放行——无人值守跑的时候用。",
        "from": "来自：{source}",
        "server_mode": "服务端是用 --permission-mode {mode} 起的：文件里的模式不作数。",
        "trying": "试试看…",
        "ok_ms": "好了：{ms} 毫秒",
        "saved": "已保存到 {path}",
        "no_key": "没有设置 key",
        "not_set": "没设置",
        "not_an_alias": "这个模型不是文件里的别名，就按原样调用",
        "tools_ok": "没问题，模型会调工具",
        "tools_failed": "模型没有调工具",
        "not_tried": "没试",
        "row_model": "模型",
        "row_api_base": "接口地址",
        "row_api_key": "key",
        "row_aliases": "别名文件",
        "row_tools": "工具",
        "key_set": "已设置（{hint}）——点一下显示",
        "key_not_set": "没设置——点一下显示",
        "key_of_endpoint": "这个地址的 key",
        "field_session_id": "会话 id",
        "field_model": "模型",
        "field_tokens": "token 数",
        "field_window": "上下文窗口",
        "field_cost": "花费",
        "field_cwd": "目录",
        "field_mode": "模式",
        "field_state": "状态",
        "field_sandbox": "沙箱",
        "field_busy": "正忙",
    },
}
"""The strings the browser shows. The templates have their own text."""


def country_of(request: Any) -> str:
    """The country of the visitor: the header of the proxy, or the geoip database."""
    for header in COUNTRY_HEADERS:
        value = request.headers.get(header, "").strip().upper()
        if value and value not in UNKNOWN_COUNTRIES:
            return value
    return _geoip_country(request.client.host if request.client else "")


_READER: Any = None
"""The geoip database, opened once."""


def _geoip_country(address: str) -> str:
    """The country of an address, with the geoip database, if there is one."""
    global _READER
    try:
        import geoip2.database
        import geoip2.errors
    except ImportError:
        return ""
    if _READER is None:
        path = Path(os.getenv(GEOIP_ENV) or config_home() / "GeoLite2-Country.mmdb")
        if not path.is_file():
            return ""
        _READER = geoip2.database.Reader(str(path))
    try:
        return _READER.country(address).country.iso_code or ""
    except geoip2.errors.AddressNotFoundError:
        return ""


def _preferred_language(header: str, available: Sequence[str]) -> str:
    """The language of the `accept-language` header, the one with the best quality."""
    best, quality = "", 0.0
    for part in header.split(","):
        name, _, parameters = part.strip().partition(";")
        weight = 1.0
        for parameter in parameters.split(";"):
            key, _, value = parameter.strip().partition("=")
            if key == "q":
                weight = float(value or 0)
        code = name.strip().lower().split("-")[0]
        if code in available and weight > quality:
            best, quality = code, weight
    return best


def _fallback(available: Sequence[str]) -> str:
    """The language of the pages when nothing else says which one."""
    if DEFAULT_LANGUAGE in available:
        return DEFAULT_LANGUAGE
    return available[0] if available else DEFAULT_LANGUAGE


def locale_of(request: Any, available: Sequence[str] = (DEFAULT_LANGUAGE,)) -> str:
    """The language of the pages.

    The choice of the visitor comes first (`?lang=` and the cookie of the
    button in the top bar), then the region of the address, then the language
    the browser asks for. A language that is not offered is ignored.
    """
    choice = request.query_params.get("lang", "").strip().lower()
    if choice in available:
        return choice
    cookie = request.cookies.get(COOKIE, "")
    if cookie in available:
        return cookie
    country = country_of(request)
    if country:
        language = REGION_LANGUAGES.get(country, "")
        return language if language in available else _fallback(available)
    return _preferred_language(request.headers.get("accept-language", ""), available) or _fallback(available)
