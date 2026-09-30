"""Front page layout and logo (#31)."""
import re
import xml.etree.ElementTree as ET
from pathlib import Path

PUBLIC = Path(__file__).resolve().parent.parent / "public"
CSS = (PUBLIC / "styles.css").read_text()


def rule(selector: str) -> str:
    match = re.search(rf"(?m)^{re.escape(selector)} \{{(.*?)\}}", CSS, re.S)
    assert match, selector
    return match.group(1)


def test_header_and_page_share_one_width():
    assert "--page-width:" in rule(":root")
    for selector in (".app-main", ".app-header-inner"):
        assert "max-width: var(--page-width)" in rule(selector), selector
        assert "padding" in rule(selector) and "margin: 0 auto" in rule(selector)


def test_header_holds_the_logo_and_tools_inside_the_page_width():
    html = (PUBLIC / "index.html").read_text()
    inner = html.split('class="app-header-inner"', 1)[1].split("</header>", 1)[0]
    assert 'class="brand"' in inner and 'class="header-tools"' in inner
    assert '<svg class="brand-mark"' in inner and 'aria-hidden="true"' in inner
    assert '<link rel="icon" href="favicon.svg"' in html


def test_favicon_is_a_valid_svg():
    root = ET.parse(PUBLIC / "favicon.svg").getroot()
    assert root.tag.endswith("svg") and root.get("viewBox") == "0 0 32 32"


def test_new_project_card_starts_level_with_the_list():
    page = rule(".projects-page")
    assert '"title ."' in page and '"list form"' in page
    assert "display: contents" in rule(".projects-main")
