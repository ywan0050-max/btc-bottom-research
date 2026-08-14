import json
from pathlib import Path

from app.config import APP_LICENSE, LICENSE_PATH, PROJECT_ROOT, SOURCE_REPOSITORY


def test_agpl_license_is_complete_and_consistent() -> None:
    text = LICENSE_PATH.read_text(encoding="utf-8")
    assert len(text) > 34_000
    assert "GNU AFFERO GENERAL PUBLIC LICENSE" in text
    assert "Version 3, 19 November 2007" in text
    assert (
        "13. Remote Network Interaction; Use with the GNU General Public License."
        in text
    )
    assert "END OF TERMS AND CONDITIONS" in text
    assert APP_LICENSE == "AGPL-3.0-only"

    package = json.loads((PROJECT_ROOT / "web" / "package.json").read_text("utf-8"))
    lock = json.loads(
        (PROJECT_ROOT / "web" / "package-lock.json").read_text("utf-8")
    )
    assert package["license"] == APP_LICENSE
    assert lock["packages"][""]["license"] == APP_LICENSE
    assert package["homepage"] == SOURCE_REPOSITORY
    assert package["repository"]["url"] == f"git+{SOURCE_REPOSITORY}.git"
    assert lock["packages"][""]["homepage"] == SOURCE_REPOSITORY
    assert lock["packages"][""]["repository"]["url"] == (
        f"git+{SOURCE_REPOSITORY}.git"
    )


def test_readme_and_notice_separate_code_and_data_terms() -> None:
    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    notice = (PROJECT_ROOT / "NOTICE.md").read_text(encoding="utf-8")
    assert "AGPL-3.0-only" in readme
    assert "第三方数据" in readme
    assert "AGPL-3.0-only" in notice
    assert "CC BY-NC 4.0" in notice
    assert SOURCE_REPOSITORY in readme


def test_running_ui_links_to_corresponding_source() -> None:
    app_source = (PROJECT_ROOT / "web" / "src" / "App.jsx").read_text(
        encoding="utf-8"
    )
    assert SOURCE_REPOSITORY in app_source
    assert "对应源代码" in app_source
