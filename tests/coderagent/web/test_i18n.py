"""The language of the pages: the region of the visitor and the choice of the visitor."""

import pytest

pytest.importorskip("fastapi")

from coderagent.web.i18n import COOKIE  # noqa: E402


def test_a_chinese_region_gets_the_chinese_pages(make_client):
    client = make_client()

    answer = client.get("/", headers={"CF-IPCountry": "CN"})

    assert 'lang="zh"' in answer.text
    assert "新会话" in answer.text


def test_a_region_that_is_not_chinese_gets_the_english_pages(make_client):
    client = make_client()

    answer = client.get("/", headers={"CF-IPCountry": "DE"})

    assert 'lang="en"' in answer.text
    assert "New session" in answer.text


def test_the_regions_of_the_chinese_language(make_client):
    client = make_client()

    for country in ("CN", "HK", "MO", "TW"):
        assert 'lang="zh"' in client.get("/", headers={"CF-IPCountry": country}).text


def test_the_visitor_can_ask_for_a_language(make_client):
    client = make_client()

    answer = client.get("/?lang=zh", headers={"CF-IPCountry": "DE"})

    assert 'lang="zh"' in answer.text


def test_the_choice_of_the_visitor_is_remembered(make_client):
    client = make_client()

    answer = client.get("/lang/zh?next=/settings", follow_redirects=False)

    assert answer.status_code == 303
    assert answer.headers["location"] == "/settings"
    assert COOKIE in answer.cookies
    assert 'lang="zh"' in client.get("/settings").text


def test_the_choice_of_the_visitor_wins_over_the_region(make_client):
    client = make_client()

    client.get("/lang/en")
    answer = client.get("/", headers={"CF-IPCountry": "CN"})

    assert 'lang="en"' in answer.text


def test_the_language_of_the_browser_is_the_last_thing(make_client):
    client = make_client()

    answer = client.get("/", headers={"accept-language": "zh-CN,zh;q=0.9,en;q=0.8"})

    assert 'lang="zh"' in answer.text


def test_a_browser_that_asks_for_english_gets_english(make_client):
    client = make_client()

    answer = client.get("/", headers={"accept-language": "en-US,en;q=0.9"})

    assert 'lang="en"' in answer.text


def test_a_proxy_that_does_not_know_the_country_says_nothing(make_client):
    client = make_client()

    answer = client.get("/", headers={"CF-IPCountry": "XX", "accept-language": "zh"})

    assert 'lang="zh"' in answer.text
