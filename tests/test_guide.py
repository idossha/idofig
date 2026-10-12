"""The docs an agent reads and the skill that points to them (idofig 0.13.0, 2026-10-11):
``idofig docs`` says where this idofig's agents.md, producers.md and SPEC.md are (shipped in the
wheel, read from the checkout otherwise); ``idofig skill install`` writes the pointer skill and
never writes over another owner's — a link (a dotfiles copy, which a write would change through
the link) or a file without the managed marker.

Reproduce: `.venv/bin/python -m pytest tests/test_guide.py`.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from idofig import cli, guide
from idofig.errors import IdofigError

REPO = Path(__file__).resolve().parents[1]


def test_docs_name_every_file_an_agent_reads_and_the_wheel_ships_them():
    paths = guide.doc_paths()
    assert set(paths) == {"agents", "producers", "spec", "readme", "changelog"}
    assert all(p.is_file() for p in paths.values())
    shipped = tomllib.loads((REPO / "pyproject.toml").read_text())["tool"]["hatch"]["build"]["targets"]["wheel"][
        "force-include"]
    assert {Path(dst).name for dst in shipped.values()} == {Path(p).name for p in guide.DOCS.values()}
    assert all((REPO / src).is_file() for src in shipped), "every shipped doc exists in the repository"


def test_the_skill_points_at_docs_that_exist_and_holds_no_api():
    text = guide.skill_text()
    assert text.startswith("---\nname: idofig\n") and guide.SKILL_MARKER in text
    for name in ("agents.md", "producers.md", "SPEC.md"):
        assert name in text and any(p.name == name for p in guide.doc_paths().values())
    assert "neuro." not in text, "the API lives in agents.md, versioned with the code, not in the skill"
    agents = guide.doc_paths()["agents"].read_text()
    assert "neuro.surface" in agents and "idf.image" in agents


def test_install_writes_each_skill_root_once_and_rewrites_only_its_own(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".agents" / "skills").mkdir(parents=True)
    assert cli.main(["skill", "install"]) == 0
    claude, agents = (tmp_path / d / "skills" / "idofig" / "SKILL.md" for d in (".claude", ".agents"))
    assert claude.read_text() == guide.skill_text() == agents.read_text()
    assert "written" in capsys.readouterr().out
    assert cli.main(["skill", "install"]) == 0
    assert capsys.readouterr().out.count("current") == 2
    claude.write_text(claude.read_text() + "\nan older version\n")  # still marked: idofig's own
    assert [r["action"] for r in guide.install_skill([claude])] == ["updated"]


def test_install_refuses_a_link_or_a_users_file_and_force_replaces_the_link_not_its_target(tmp_path):
    owner = tmp_path / "dotfiles" / "idofig"
    owner.mkdir(parents=True)
    (owner / "SKILL.md").write_text("the user's own skill\n")
    linked = tmp_path / "linked"
    linked.mkdir()
    os.symlink(owner, linked / "idofig")
    mine = tmp_path / "users" / "idofig" / "SKILL.md"
    mine.parent.mkdir(parents=True)
    mine.write_text("written by hand\n")
    targets = guide.skill_targets(dirs=[str(linked), str(tmp_path / "users"), str(tmp_path / "fresh")])
    with pytest.raises(IdofigError, match="is a link to.*no managed marker"):
        guide.install_skill(targets)
    assert not (tmp_path / "fresh").exists(), "checked before anything is written"
    rows = guide.install_skill(targets, force=True)
    assert [r["action"] for r in rows] == ["written", "updated", "written"]
    assert (owner / "SKILL.md").read_text() == "the user's own skill\n", "the link's target is untouched"
    assert not (linked / "idofig").is_symlink() and (linked / "idofig" / "SKILL.md").read_text() == guide.skill_text()


def test_install_into_a_project(project, capsys):
    assert cli.main(["skill", "install", "--project"]) == 0
    assert (project.root / ".claude" / "skills" / "idofig" / "SKILL.md").read_text() == guide.skill_text()


def test_docs_and_skill_import_nothing_heavy():
    probe = ("import sys\nfrom idofig import cli\ncli.main(['docs', 'spec'])\n"
             "print(sorted(m for m in ('matplotlib', 'numpy', 'mne', 'nibabel') if m in sys.modules))\n")
    out = subprocess.run([sys.executable, "-c", probe], check=True, capture_output=True, text=True).stdout
    assert out.splitlines()[0].endswith("SPEC.md") and out.splitlines()[-1] == "[]"
