"""github-mod-fetch: tag-derived version, MO2 .meta layout, asset choice, DLL wrapping, refusals. Offline."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import zipfile

import pytest

from conftest import REPO

TOOL = REPO / "tools" / "github-mod-fetch.py"
_spec = importlib.util.spec_from_file_location("github_mod_fetch", TOOL)
gmf = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gmf)

DLL = b"MZ" + b"\0" * 100
PDB = b"pdb-bytes"


def asset(name, data, digest=True):
    a = {"name": name, "size": len(data), "browser_download_url": f"https://github.com/o/r/releases/download/x/{name}"}
    if digest:
        a["digest"] = "sha256:" + hashlib.sha256(data).hexdigest()
    return a


class FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def github(monkeypatch, tmp_path):
    """Serve one release; record request URLs. Protected roots point into tmp so the real config is not read."""
    state = {"release": None, "blobs": {}, "urls": []}

    def urlopen(req, timeout=None):
        url = req.full_url
        state["urls"].append(url)
        if url.startswith(gmf.API):
            if state["release"] is None:
                raise gmf.urllib.error.HTTPError(url, 404, "nf", {}, None)
            return FakeResp(json.dumps(state["release"]).encode())
        return FakeResp(state["blobs"][url.rsplit("/", 1)[1]])

    monkeypatch.setattr(gmf.urllib.request, "urlopen", urlopen)
    monkeypatch.setenv("SKYRIM_GAME_ROOT", str(tmp_path / "game"))
    monkeypatch.setenv("SKYRIM_MO2_MODS", str(tmp_path / "MO2" / "mods"))
    monkeypatch.setenv("SKYRIM_MO2_OVERWRITE", str(tmp_path / "MO2" / "overwrite"))
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)

    def serve(tag, files, digest=True):
        state["release"] = {"tag_name": tag, "assets": [asset(n, d, digest) for n, d in files]}
        state["blobs"] = dict(files)

    state["serve"] = serve
    return state


def fetch(tmp_path, *extra):
    return gmf.run(["o/r", "--mod-category", "95", "--out", str(tmp_path / "dl"), *extra])


# ---------------------------------------------------------------- version follows the tag

@pytest.mark.parametrize("tag,version", [("v1.1", "1.1"), ("1.2.0", "1.2.0"), ("V2.0.3", "2.0.3"),
                                         ("v1.0-beta2", "1.0-beta2"), ("1.0.0.4", "1.0.0.4")])
def test_version_is_the_tag_minus_one_leading_v(tag, version):
    assert gmf.tag_version(tag) == version


@pytest.mark.parametrize("tag", ["latest", "nightly", "v", ""])
def test_tag_without_a_version_is_refused(tag):
    with pytest.raises(gmf.Refused):
        gmf.tag_version(tag)


def test_tag_option_asks_for_that_release(github, tmp_path):
    github["serve"]("v0.9", [("A.dll", DLL)])
    assert fetch(tmp_path, "--tag", "v0.9", "--dry-run") == 0
    assert github["urls"][0].endswith("/repos/o/r/releases/tags/v0.9")


# ---------------------------------------------------------------- .meta layout

EXPECTED_META = (
    "[General]\r\ngameName=SkyrimSE\r\nmodID=169302\r\nmodName=My Mod\r\nversion=1.1\r\nnewestVersion=1.1\r\n"
    "installed=false\r\nfileID=0\r\nurl=\r\nname=A.dll\r\ndescription=\r\n"
    "fileTime=@DateTime(\\0\\0\\0\\x10\\0\\x80\\0\\0\\0\\0\\0\\0\\0\\xff\\xff\\xff\\xff\\0)\r\n"
    "fileCategory=3\r\ncategory=95\r\nrepository=\r\nuserData=@Variant(\\0\\0\\0\\b\\0\\0\\0\\0)\r\n"
    "author=\r\nuploader=\r\nuploaderUrl=\r\nuninstalled=false\r\npaused=false\r\nremoved=false\r\n")


def test_meta_matches_the_mo2_layout_byte_for_byte():
    meta = gmf.download_meta(mod_id=169302, mod_name="My Mod", version="1.1", file_category=3, mod_category=95,
                             file_name="A.dll")
    assert meta == EXPECTED_META


def test_meta_quotes_a_name_qsettings_would_split():
    meta = gmf.download_meta(mod_id=0, mod_name="Fix, Again", version="1", file_category=1, mod_category=95)
    assert 'modName="Fix, Again"\r\n' in meta


# ---------------------------------------------------------------- packaging

def test_bare_dll_is_wrapped_into_skse_plugins_with_companion_and_meta(github, tmp_path):
    github["serve"]("v1.1", [("A.dll", DLL), ("A.pdb", PDB), ("README.txt", b"r")])
    assert fetch(tmp_path, "--nexus-id", "7") == 0
    out = tmp_path / "dl"
    archive = out / "r-1.1.zip"
    with zipfile.ZipFile(archive) as zf:
        assert sorted(zf.namelist()) == ["SKSE/Plugins/A.dll", "SKSE/Plugins/A.pdb", "meta.ini"]
        assert zf.read("SKSE/Plugins/A.dll") == DLL
        ini = zf.read("meta.ini").decode()
    assert "version=1.1\r\n" in ini and "modid=7\r\n" in ini
    assert "url=https://github.com/o/r\r\nhasCustomURL=true\r\n" in ini
    meta = (out / "r-1.1.zip.meta").read_bytes().decode()
    assert "version=1.1\r\n" in meta and "modID=7\r\n" in meta and "category=95\r\n" in meta


def test_plugin_goes_to_the_zip_root(github, tmp_path):
    github["serve"]("v2", [("Patch.esp", b"TES4")])
    assert fetch(tmp_path) == 0
    with zipfile.ZipFile(tmp_path / "dl" / "r-2.zip") as zf:
        assert sorted(zf.namelist()) == ["Patch.esp", "meta.ini"]


def test_archive_asset_is_kept_byte_for_byte(github, tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("SKSE/Plugins/A.dll", DLL)
    github["serve"]("v3.0", [("A-3.0.zip", buf.getvalue())])
    assert fetch(tmp_path) == 0
    assert (tmp_path / "dl" / "A-3.0.zip").read_bytes() == buf.getvalue()
    assert b"version=3.0\r\n" in (tmp_path / "dl" / "A-3.0.zip.meta").read_bytes()


def test_archive_without_a_data_root_warns(github, tmp_path, capsys):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("Wrapper/SKSE/Plugins/A.dll", DLL)
    github["serve"]("v1", [("A.zip", buf.getvalue())])
    assert fetch(tmp_path) == 0
    assert "WARNING" in capsys.readouterr().out


# ---------------------------------------------------------------- refusals and failures

def test_several_installable_assets_need_asset(github, tmp_path, capsys):
    github["serve"]("v1", [("A.dll", DLL), ("A-full.zip", b"PK")])
    assert fetch(tmp_path) == 2
    assert "--asset" in capsys.readouterr().err
    assert fetch(tmp_path, "--asset", "A.dll") == 0


def test_source_only_release_is_refused(github, tmp_path):
    github["serve"]("v1", [("notes.txt", b"x")])
    assert fetch(tmp_path) == 2


def test_no_release_is_refused(github, tmp_path):
    assert fetch(tmp_path) == 2


def test_mod_category_is_required(github, tmp_path):
    github["serve"]("v1", [("A.dll", DLL)])
    assert gmf.run(["o/r", "--out", str(tmp_path / "dl")]) == 2
    assert gmf.run(["o/r", "--mod-category", "0", "--out", str(tmp_path / "dl")]) == 2


def test_digest_mismatch_fails_and_writes_nothing(github, tmp_path):
    github["serve"]("v1", [("A.dll", DLL)])
    github["release"]["assets"][0]["digest"] = "sha256:" + "0" * 64
    assert fetch(tmp_path) == 1
    assert not (tmp_path / "dl" / "r-1.zip").exists()


def test_existing_files_are_not_overwritten_without_force(github, tmp_path):
    github["serve"]("v1", [("A.dll", DLL)])
    assert fetch(tmp_path) == 0
    assert fetch(tmp_path) == 2
    assert fetch(tmp_path, "--force") == 0


def test_dry_run_downloads_and_writes_nothing(github, tmp_path):
    github["serve"]("v1", [("A.dll", DLL)])
    assert fetch(tmp_path, "--dry-run") == 0
    assert all(u.startswith(gmf.API) for u in github["urls"])
    assert not (tmp_path / "dl").exists()


@pytest.mark.parametrize("sub", ["game/Data", "MO2/mods/X", "MO2/overwrite", "MO2/downloads"])
def test_game_and_mo2_folders_are_refused(github, tmp_path, sub):
    github["serve"]("v1", [("A.dll", DLL)])
    assert gmf.run(["o/r", "--mod-category", "95", "--out", str(tmp_path / sub)]) == 2


@pytest.mark.parametrize("text", ["o/r", "https://github.com/o/r", "github.com/o/r.git",
                                  "https://github.com/o/r/releases/tag/v1"])
def test_repo_forms(text):
    assert gmf.parse_repo(text) == ("o", "r")


def test_linux_downloads_dir_reads_xdg(monkeypatch, tmp_path):
    monkeypatch.setattr(gmf.os, "name", "posix")
    monkeypatch.setattr(gmf.sys, "platform", "linux")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    (tmp_path / "user-dirs.dirs").write_text('XDG_DOWNLOAD_DIR="$HOME/Telechargements"\n')
    assert gmf.downloads_dir() == gmf.Path.home() / "Telechargements"
