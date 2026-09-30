"""The mockup viewer's heading shows a version only for a saved mockup (#30)."""
import re
from pathlib import Path

PUBLIC = Path(__file__).resolve().parent.parent / "public" / "js"


def test_unsaved_previews_pass_no_placeholder_version():
    source = (PUBLIC / "views" / "chat.js").read_text()
    calls = re.findall(r"openMockupViewer\(\{[^}]*\}", source)
    assert calls, "chat.js no longer opens the viewer"
    assert not [call for call in calls if "version" in call]


def test_viewer_prints_a_version_only_when_there_is_one():
    source = (PUBLIC / "mockup" / "viewer.js").read_text()
    heading = re.search(r"mount\(heading, (.*?)\);", source, re.S).group(1)
    assert "shown.number ?" in heading or "shown.number &&" in heading
