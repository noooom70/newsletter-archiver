"""Tests for SafeLink unwrapping and tracking-param stripping."""

from bs4 import BeautifulSoup

from newsletter_archiver.fetcher.link_cleaner import clean_links, clean_url

SAFELINK = (
    "https://na01.safelinks.protection.outlook.com/?url="
    "https%3A%2F%2Fstratechery.com%2F2026%2Fexample-article%2F"
    "%3Faccess_token%3DSYNTH.TOKEN.VALUE"
    "&data=05%7C02%7CSYNTHDATA&sdata=SYNTHSIG&reserved=0"
)


def test_clean_url_unwraps_safelink():
    url, failed = clean_url(SAFELINK)
    assert url == "https://stratechery.com/2026/example-article/"
    assert failed is False


def test_clean_url_strips_tracking_params_from_plain_url():
    url, failed = clean_url(
        "https://click.e.economist.com/u/?qs=SYNTHTRACKER&m=123"
    )
    assert url == "https://click.e.economist.com/u/"
    assert failed is False


def test_clean_url_keeps_youtube_v_param():
    url, _ = clean_url("https://www.youtube.com/watch?v=abc123&si=TRACK")
    assert url == "https://www.youtube.com/watch?v=abc123"


def test_clean_url_keeps_fragment():
    url, _ = clean_url("https://example.com/page?utm_source=x#section-2")
    assert url == "https://example.com/page#section-2"


def test_clean_url_safelink_missing_url_param_fails_open():
    original = "https://na01.safelinks.protection.outlook.com/?data=05%7C02"
    url, failed = clean_url(original)
    assert url == original
    assert failed is True


def test_clean_url_safelink_non_http_destination_fails_open():
    original = (
        "https://na01.safelinks.protection.outlook.com/?url=javascript%3Aalert(1)"
    )
    url, failed = clean_url(original)
    assert url == original
    assert failed is True


def test_clean_url_nested_redirect_unwraps_one_level_only():
    # Outer SafeLink unwraps; the publisher's own ?url= redirect param is a
    # tracking-strippable param (not in keeplist), so it gets stripped.
    wrapped = (
        "https://na01.safelinks.protection.outlook.com/?url="
        "https%3A%2F%2Fpublisher.example%2Fredirect%3Furl%3Dhttps%253A%252F%252Ffinal.example"
    )
    url, failed = clean_url(wrapped)
    assert url == "https://publisher.example/redirect"
    assert failed is False


def test_clean_url_encodes_markdown_breaking_chars():
    url, _ = clean_url("https://en.wikipedia.org/wiki/Foo_(bar)")
    assert url == "https://en.wikipedia.org/wiki/Foo_%28bar%29"


def test_clean_url_plain_url_without_query_untouched():
    url, failed = clean_url("https://example.com/article")
    assert url == "https://example.com/article"
    assert failed is False


def test_clean_links_rewrites_all_hrefs():
    soup = BeautifulSoup(
        f'<p><a href="{SAFELINK}">Read</a>'
        '<a href="https://x.example/a?qs=T">Other</a>'
        "<a>no href</a></p>",
        "html.parser",
    )
    failures = clean_links(soup)
    assert failures == 0
    hrefs = [a.get("href") for a in soup.find_all("a")]
    assert hrefs[0] == "https://stratechery.com/2026/example-article/"
    assert hrefs[1] == "https://x.example/a"
    assert hrefs[2] is None


def test_clean_links_counts_unwrap_failures():
    bad = "https://na01.safelinks.protection.outlook.com/?data=05"
    soup = BeautifulSoup(f'<a href="{bad}">x</a>', "html.parser")
    assert clean_links(soup) == 1
    assert soup.find("a")["href"] == bad
