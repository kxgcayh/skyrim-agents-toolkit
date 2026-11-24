"""tools/loot_advisor.py and tools/libloot/: LOOT's advice on the active order, read-only, against a fake libloot.

The real libloot is exercised by the E2E run on a real install (docs/loot.md); here a fake `loot` module records every
call, so "never writes the load order" is a test: the fake raises if anything asks it to set an order, and the
load-order files are byte-identical afterwards."""
import base64
import hashlib
import json
from pathlib import Path
import sys
import types
import zipfile
import subprocess
import struct

import pytest

from conftest import REPO
sys.path.insert(0, str(REPO / "tools"))
import loot_advisor  # noqa: E402
from libloot import build as libloot_build  # noqa: E402
from libloot import libloot_loader  # noqa: E402


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """No test here reaches the real GitHub: a leak once passed for weeks and failed only when CI was rate-limited.
    A test that exercises _get itself patches urlopen again, which wins."""
    def refuse(*a, **k):
        raise AssertionError("a LOOT test reached the real network")
    monkeypatch.setattr(loot_advisor.urllib.request, "urlopen", refuse)


# ---- moves

@pytest.mark.parametrize("current,proposed,moved", [
    (["a", "b", "c"], ["a", "b", "c"], []),
    (["a", "b", "c", "d"], ["a", "c", "b", "d"], ["c"]),          # one swap: the fewest moves names one plugin
    (["a", "b", "c", "d"], ["b", "c", "d", "a"], ["a"]),
])
def test_moves_names_the_fewest_plugins_whose_position_changes(current, proposed, moved):
    assert [m["plugin"] for m in loot_advisor.moves(current, proposed)] == moved


def test_a_reversal_moves_all_but_one():
    """Any one plugin may stay (each is a longest shared run of length 1): the count is fixed, the choice is not."""
    got = [m["plugin"] for m in loot_advisor.moves(["a", "b", "c"], ["c", "b", "a"])]
    assert len(got) == 2 and len(set(got)) == 2


def test_a_move_says_what_it_lands_after():
    [m] = loot_advisor.moves(["a", "b", "c", "d"], ["a", "c", "b", "d"])
    assert (m["from"], m["to"], m["after"]) == (2, 1, "a")


# ---- masterlist fetch and cache

def _branches(*rows):
    return json.dumps([{"name": n, "commit": {"sha": s}} for n, s in rows]).encode()


class Net:
    """Fake GitHub: branch lists per repo and file bytes per (repo, commit, file); `down` makes every call fail."""

    def __init__(self, ml_commit="a" * 40, pre_commit="b" * 40):
        self.down = False
        self.calls = []
        self.branches = {"skyrimvr": _branches(("v0.21", ml_commit), ("v0.26", "f" * 40), ("master", "e" * 40)),
                         "prelude": _branches(("v0.21", pre_commit))}

    def __call__(self, url, timeout=20.0):
        self.calls.append(url)
        if self.down:
            raise OSError("network is down")
        for repo, body in self.branches.items():
            if url == loot_advisor.API.format(repo=repo):
                return body
        return ("BYTES " + url.rsplit("/", 2)[-2]).encode()


def test_the_newest_branch_this_libloot_reads_is_chosen():
    net = Net()
    assert loot_advisor.newest_branch("skyrimvr", (0, 21), net) == ("v0.21", "a" * 40)
    assert loot_advisor.newest_branch("skyrimvr", (0, 29), net) == ("v0.26", "f" * 40)
    with pytest.raises(ValueError):
        loot_advisor.newest_branch("skyrimvr", (0, 20), net)


def test_a_fetch_is_cached_and_a_later_failure_uses_the_cache_and_says_so(tmp_path):
    net = Net()
    ml, pre, src = loot_advisor.masterlist("SkyrimVR", (0, 21), fetch=net, cache=tmp_path)
    assert ml.read_bytes() == b"BYTES " + b"a" * 40 and pre.read_bytes() == b"BYTES " + b"b" * 40
    assert src["from_cache"] is False and src["masterlist"]["commit"] == "a" * 40
    net.down = True
    ml2, _, src2 = loot_advisor.masterlist("SkyrimVR", (0, 21), fetch=net, cache=tmp_path)
    assert ml2 == ml and src2["from_cache"] is True and "network is down" in src2["fetch_problem"]


def test_no_fetch_and_no_cache_is_an_error_never_an_empty_masterlist(tmp_path):
    net = Net()
    net.down = True
    with pytest.raises(ValueError, match="no masterlist"):
        loot_advisor.masterlist("SkyrimVR", (0, 21), fetch=net, cache=tmp_path)
    with pytest.raises(ValueError, match="no masterlist"):
        loot_advisor.masterlist("SkyrimVR", (0, 21), offline=True, fetch=net, cache=tmp_path)


def test_offline_makes_no_network_call(tmp_path):
    net = Net()
    loot_advisor.masterlist("SkyrimVR", (0, 21), fetch=net, cache=tmp_path)
    net.calls.clear()
    _, _, src = loot_advisor.masterlist("SkyrimVR", (0, 21), offline=True, fetch=net, cache=tmp_path)
    assert net.calls == [] and src["from_cache"] is True


def test_the_cache_keeps_the_current_and_previous_masterlist_only(tmp_path):
    for i, c in enumerate("abc"):
        net = Net(ml_commit=c * 40)
        loot_advisor.masterlist("SkyrimVR", (0, 21), fetch=net, cache=tmp_path)
    kept = sorted(p.name[:1] for p in (tmp_path / "skyrimvr").iterdir() if p.is_dir())
    assert kept == ["b", "c"]


# ---- the advice, against a fake libloot

class Msg:
    def __init__(self, kind, text):
        self.message_type, self.content = "MessageType." + kind, [types.SimpleNamespace(text=text)]


class File:
    def __init__(self, name, display=""):
        self.name, self.display_name = name, display


class FakeLoot(types.SimpleNamespace):
    """The libloot surface loot_advisor uses. Any order-writing call raises."""

    def __init__(self, order, active, proposed, metadata=None, general=()):
        super().__init__(LIBLOOT_VERSION_MAJOR=0, LIBLOOT_VERSION_MINOR=21,
                         GameType=types.SimpleNamespace(SkyrimVR="vr", SkyrimSE="se"))
        fake = self

        class Db:
            def load_masterlist_with_prelude(self, ml, pre):
                fake.loaded = (Path(ml).name, Path(pre).name)

            def load_userlist(self, path):
                fake.userlist = Path(path)

            def general_messages(self, *a):
                return list(general)

            def plugin_metadata(self, name, *a):
                return (metadata or {}).get(name)

        class Game:
            def __init__(self, kind, game, local):
                fake.game_args = (kind, game, local)

            def __getattr__(self, name):
                if "set" in name and "order" in name or name in ("save", "write"):
                    raise AssertionError("the advisor asked libloot to " + name)
                raise AttributeError(name)

            def set_additional_data_paths(self, paths):
                fake.extra = paths

            def load_current_load_order_state(self):
                pass

            def load_order(self):
                return list(order)

            def is_plugin_active(self, p):
                return p in active

            def load_plugins(self, paths):
                fake.plugins = [Path(p).name for p in paths]

            def database(self):
                return Db()

            def sort_plugins(self, plugins):
                fake.sorted = list(plugins)
                return list(proposed)
        self.Game = Game

    def libloot_version(self):
        return "0.29.7"

    def libloot_revision(self):
        return "c242698"

    def select_message_content(self, content, lang):
        return content[0]


@pytest.fixture
def install(tmp_path):
    game = tmp_path / "game"
    (game / "Data").mkdir(parents=True)
    (game / "SkyrimVR.exe").write_bytes(b"")
    local = tmp_path / "local"
    local.mkdir()
    names = ["Skyrim.esm", "A.esp", "B.esp", "Off.esp"]
    for n in names:
        (game / "Data" / n).write_bytes(b"TES4")
    (local / "Plugins.txt").write_text("*Skyrim.esm\n*A.esp\n*B.esp\nOff.esp\n", encoding="utf-8")
    (local / "loadorder.txt").write_text("\n".join(names) + "\n", encoding="utf-8")
    return game, local, names


def _advise(install, tmp_path, fake):
    game, local, _ = install
    net = Net()
    cache = tmp_path / "cache"
    old = loot_advisor.CACHE
    loot_advisor.CACHE = cache
    try:
        return loot_advisor.advise(local / "Plugins.txt", game / "Data", game, [], loot=fake,
                                   fetch=lambda url, timeout=20.0: net(url))
    finally:
        loot_advisor.CACHE = old


def test_the_advice_never_writes_the_load_order(install, tmp_path):
    game, local, names = install
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in local.iterdir()}
    fake = FakeLoot(names, {"Skyrim.esm", "A.esp", "B.esp"}, ["Skyrim.esm", "B.esp", "A.esp"])
    report = _advise(install, tmp_path, fake)
    assert [m["plugin"] for m in report["moves"]] == ["B.esp"]
    assert fake.sorted == ["Skyrim.esm", "A.esp", "B.esp"] and fake.plugins == ["Skyrim.esm", "A.esp", "B.esp"]
    assert {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in local.iterdir()} == before
    assert "nothing was reordered" in report["note"]


def test_masterlist_messages_dirty_plugins_requirements_and_incompatibilities_are_reported(install, tmp_path):
    game, local, names = install
    (game / "Data" / "SKSE").mkdir()
    (game / "Data" / "SKSE" / "present.dll").write_bytes(b"")
    md = {"A.esp": types.SimpleNamespace(
              messages=[Msg("warn", "check this")],
              dirty_info=[types.SimpleNamespace(itm_count=3, deleted_reference_count=1, deleted_navmesh_count=0,
                                                cleaning_utility="SSEEdit")],
              requirements=[File("Missing.esm"), File("B.esp"), File("SKSE/present.dll"), File("SKSE/absent.dll")],
              incompatibilities=[File("B.esp", "B"), File("Off.esp")])}
    fake = FakeLoot(names, {"Skyrim.esm", "A.esp", "B.esp"}, ["Skyrim.esm", "A.esp", "B.esp"], md,
                    general=[Msg("say", "general note")])
    got = {(i["kind"], i.get("needs") or i.get("with") or i.get("text") or i.get("itm")) for i in
           _advise(install, tmp_path, fake)["issues"]}
    assert got == {("general", "general note"), ("message", "check this"), ("dirty", 3),
                   ("requirement-missing", "Missing.esm"), ("requirement-missing", "SKSE/absent.dll"),
                   ("incompatible", "B.esp")}       # Off.esp is not active, so it is no incompatibility


def test_no_userlist_is_loaded_unless_one_is_named_and_the_report_says_which(install, tmp_path):
    game, local, names = install
    fake = FakeLoot(names, {"Skyrim.esm", "A.esp", "B.esp"}, ["Skyrim.esm", "A.esp", "B.esp"])
    report = _advise(install, tmp_path, fake)
    assert report["userlist"] is None and not hasattr(fake, "userlist")


def test_a_named_userlist_is_loaded_after_the_masterlist_reported_with_its_hash_and_left_unchanged(install, tmp_path):
    game, local, names = install
    ul = tmp_path / "userlist.yaml"
    ul.write_text("plugins:\n  - name: A.esp\n    after: [B.esp]\n", encoding="utf-8")
    before = ul.read_bytes()
    fake = FakeLoot(names, {"Skyrim.esm", "A.esp", "B.esp"}, ["Skyrim.esm", "B.esp", "A.esp"])
    old, loot_advisor.CACHE = loot_advisor.CACHE, tmp_path / "cache"
    try:
        report = loot_advisor.advise(local / "Plugins.txt", game / "Data", game, [], loot=fake,
                                    fetch=lambda url, timeout=20.0: Net()(url), userlist=ul)
    finally:
        loot_advisor.CACHE = old
    assert fake.userlist == ul and hasattr(fake, "loaded")
    assert report["userlist"] == {"path": str(ul), "sha256": hashlib.sha256(before).hexdigest()}
    assert ul.read_bytes() == before


def test_a_userlist_path_that_is_not_a_file_is_could_not_check_before_libloot_loads(monkeypatch, capsys, install):
    game, local, names = install
    monkeypatch.setattr(loot_advisor.skyrim_paths, "game_root", lambda: (game, "test"))
    monkeypatch.setattr(loot_advisor, "_plugin_check", lambda: types.SimpleNamespace(
        mo2_folders=lambda env: ([], None), locate=lambda n, d, f: str(game / "Data" / n)))
    monkeypatch.setattr(loot_advisor.libloot_loader, "load", lambda: pytest.fail("libloot loaded"))
    assert loot_advisor.main(["--plugins-txt", str(local / "Plugins.txt"),
                              "--userlist", str(local / "nope.yaml")]) == 2
    assert "userlist not found" in capsys.readouterr().err


def test_an_active_plugin_missing_from_disk_is_could_not_check(install, tmp_path):
    game, local, names = install
    missing_game = tmp_path / 'missing-game'
    missing_data = missing_game / 'Data'
    missing_data.mkdir(parents=True)
    (missing_game / 'SkyrimVR.exe').touch()
    for name in names:
        if name != 'B.esp':
            (missing_data / name).write_bytes(b'TES4')
    fake = FakeLoot(names, {"Skyrim.esm", "A.esp", "B.esp"}, names[:3])
    with pytest.raises(ValueError, match="not on disk"):
        _advise((missing_game, local, names), tmp_path, fake)


def test_unavailable_libloot_exits_2_and_never_says_clean(monkeypatch, capsys, install):
    game, local, _ = install
    monkeypatch.setattr(loot_advisor.skyrim_paths, "game_root", lambda: (game, "test"))

    def unavailable():
        raise libloot_loader.Unavailable("no wheel here")
    monkeypatch.setattr(loot_advisor.libloot_loader, "load", unavailable)
    monkeypatch.setattr(loot_advisor, "_plugin_check", lambda: types.SimpleNamespace(mo2_folders=lambda env: ([], None)))
    assert loot_advisor.main(["--plugins-txt", str(local / "Plugins.txt"), "--offline"]) == 2
    assert "not a clean result" in capsys.readouterr().err


# ---- the loader: only a listed, matching wheel loads; its extracted copy is re-checked every time

def _b64(data):
    return base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()


def make_wheel(folder, body=b"VALUE = 'fake loot'\n", extra=None, list_it=True, platform=None, version="0.29.7"):
    tag = "cp%d%d" % sys.version_info[:2]
    plat = platform or ("win_amd64" if sys.platform == "win32" else "linux_x86_64")
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "libloot-{2}-{0}-{0}-{1}.whl".format(tag, plat, version)
    files = {"loot/__init__.py": body}
    record = "".join("%s,sha256=%s,%d\n" % (n, _b64(d), len(d)) for n, d in files.items())
    with zipfile.ZipFile(path, "w") as z:
        for n, d in files.items():
            z.writestr(n, d)
        z.writestr("libloot-%s.dist-info/RECORD" % version, record + "libloot-%s.dist-info/RECORD,,\n" % version)
        for n, d in (extra or {}).items():
            z.writestr(n, d)
    if list_it:
        (folder / "SHA256SUMS").write_text("%s *%s\n" % (hashlib.sha256(path.read_bytes()).hexdigest(), path.name))
    return path


@pytest.fixture
def fresh_import(monkeypatch):
    monkeypatch.delitem(sys.modules, "loot", raising=False)
    monkeypatch.setattr(sys, "path", list(sys.path))
    yield
    sys.modules.pop("loot", None)


def test_a_listed_wheel_loads(tmp_path, fresh_import):
    make_wheel(tmp_path / "built")
    mod = libloot_loader.load(shipped=tmp_path / "none", built=tmp_path / "built", cache=tmp_path / "cache")
    assert mod.VALUE == "fake loot"


def test_an_unlisted_or_changed_wheel_is_refused(tmp_path, fresh_import):
    make_wheel(tmp_path / "unlisted", list_it=False)
    with pytest.raises(libloot_loader.Unavailable, match="not listed"):
        libloot_loader.wheel(shipped=tmp_path / "none", built=tmp_path / "unlisted")
    path = make_wheel(tmp_path / "changed")
    path.write_bytes(path.read_bytes() + b"x")
    with pytest.raises(libloot_loader.Unavailable, match="does not match"):
        libloot_loader.wheel(shipped=tmp_path / "none", built=tmp_path / "changed")


def test_a_changed_extracted_file_is_refused(tmp_path, fresh_import):
    make_wheel(tmp_path / "built")
    kw = dict(shipped=tmp_path / "none", built=tmp_path / "built", cache=tmp_path / "cache")
    libloot_loader.load(**kw)
    sys.modules.pop("loot", None)
    [extracted] = [p for p in (tmp_path / "cache").iterdir() if p.is_dir()]
    (extracted / "loot" / "__init__.py").write_text("VALUE = 'tampered'\n")
    with pytest.raises(libloot_loader.Unavailable, match="does not match its wheel"):
        libloot_loader.load(**kw)


def test_a_wheel_member_outside_its_folder_is_refused_and_nothing_is_left(tmp_path, fresh_import):
    make_wheel(tmp_path / "built", extra={"../escape.py": b"x"})
    with pytest.raises(libloot_loader.Unavailable, match="escapes"):
        libloot_loader.load(shipped=tmp_path / "none", built=tmp_path / "built", cache=tmp_path / "cache")
    assert not (tmp_path / "escape.py").exists() and list((tmp_path / "cache").iterdir()) == []


@pytest.mark.skipif(sys.platform != "win32", reason="the shipped wheels are for Windows x64 only")
def test_a_shipped_wheel_for_another_platform_is_not_used(tmp_path):
    make_wheel(tmp_path / "shipped", platform="linux_x86_64")
    with pytest.raises(libloot_loader.Unavailable, match="no libloot [0-9.]+ wheel"):
        libloot_loader.wheel(shipped=tmp_path / "shipped", built=tmp_path / "none")


# ---- the shipped files and build.py record

def test_every_shipped_wheel_and_the_source_pack_match_their_sums():
    """The committed binaries are exactly what the CI run recorded (build.py record); the GPL source ships beside them."""
    folder = REPO / "tools" / "libloot"
    wheels = sorted((folder / "wheels").glob("*.whl"))
    assert wheels, "no shipped wheels"
    for sub, files in (("wheels", wheels), ("source", sorted((folder / "source").glob("*.tar.gz")))):
        listed = libloot_loader.sums(folder / sub)
        assert sorted(listed) == [f.name for f in files] and len(files) >= 1
        for f in files:
            assert hashlib.sha256(f.read_bytes()).hexdigest() == listed[f.name], f
    meta = json.loads((folder / "PROVENANCE.json").read_text(encoding="utf-8"))
    assert meta["build"]["run"] and all(meta["upstream"]["version"] in f.name for f in wheels)
    assert meta["upstream"]["commit"] in (REPO / ".github" / "workflows" / "libloot-wheels.yml").read_text()


def test_record_refuses_an_artifact_that_does_not_match_its_run(tmp_path):
    art = tmp_path / "art"
    make_wheel(art / "w")
    src = art / "s"
    src.mkdir()
    pack = src / "libloot-0.29.7-c242698ea86a-source.tar.gz"
    pack.write_bytes(b"pack")
    (src / "SHA256SUMS").write_text("%s *%s\n" % (hashlib.sha256(b"pack").hexdigest(), pack.name))
    prov = tmp_path / "PROVENANCE.json"
    prov.write_text(json.dumps({"upstream": {"version": "0.29.7"}, "build": {"run": None}}))
    out = libloot_build.record(art, "123", wheels=tmp_path / "wheels", source=tmp_path / "source", provenance=prov)
    assert out["source"] == pack.name and json.loads(prov.read_text())["build"]["run"] == "123"
    assert libloot_loader.sums(tmp_path / "wheels") and libloot_loader.sums(tmp_path / "source")
    pack.write_bytes(b"changed")
    with pytest.raises(SystemExit, match="does not match"):
        libloot_build.record(art, "124", wheels=tmp_path / "w2", source=tmp_path / "s2", provenance=prov)
    assert not (tmp_path / "w2").exists()


# ---- 4.1 release review fixes

def test_a_built_wheel_of_another_version_is_never_picked(tmp_path, fresh_import):
    """A stale (or newer) build left in the build folder must not beat the carried version (PROVENANCE.json)."""
    assert libloot_loader.version() == "0.29.7"
    make_wheel(tmp_path / "built", version="0.29.6", body=b"VALUE = 'stale'\n")
    if sys.platform == "win32":
        shipped = make_wheel(tmp_path / "shipped")
        assert libloot_loader.wheel(shipped=tmp_path / "shipped", built=tmp_path / "built") == shipped
    else:
        with pytest.raises(libloot_loader.Unavailable, match="no libloot 0.29.7 wheel"):
            libloot_loader.wheel(shipped=tmp_path / "shipped", built=tmp_path / "built")


def test_a_file_the_wheel_does_not_hold_is_refused(tmp_path, fresh_import):
    make_wheel(tmp_path / "built")
    kw = dict(shipped=tmp_path / "none", built=tmp_path / "built", cache=tmp_path / "cache")
    libloot_loader.load(**kw)
    sys.modules.pop("loot", None)
    [extracted] = [p for p in (tmp_path / "cache").iterdir() if p.is_dir()]
    (extracted / "json.py").write_text("planted = True\n")
    with pytest.raises(libloot_loader.Unavailable, match="does not"):
        libloot_loader.load(**kw)


def test_a_plugins_file_with_another_name_is_refused(install, tmp_path):
    game, local, names = install
    other = local / "test-order.txt"
    other.write_text("*Skyrim.esm\n", encoding="utf-8")
    fake = FakeLoot(names, {"Skyrim.esm"}, ["Skyrim.esm"])
    with pytest.raises(ValueError, match="(?i)named plugins.txt"):
        loot_advisor.advise(other, game / "Data", game, [], loot=fake, fetch=Net())


def test_a_cached_masterlist_this_libloot_cannot_read_is_not_used(tmp_path):
    net = Net()
    loot_advisor.masterlist("SkyrimVR", (0, 29), fetch=net, cache=tmp_path)      # caches branch v0.26
    net.down = True
    with pytest.raises(ValueError, match="does not read"):
        loot_advisor.masterlist("SkyrimVR", (0, 21), fetch=net, cache=tmp_path)


def test_a_fresh_masterlist_that_does_not_parse_never_becomes_the_cache(tmp_path):
    net = Net()
    loot_advisor.masterlist("SkyrimVR", (0, 21), fetch=net, cache=tmp_path)
    meta = (tmp_path / "skyrimvr" / "meta.json").read_bytes()
    net2 = Net(ml_commit="c" * 40)

    def bad(ml, pre):
        raise RuntimeError("unknown key")
    ml, _, src = loot_advisor.masterlist("SkyrimVR", (0, 21), fetch=net2, cache=tmp_path, validate=bad)
    assert src["from_cache"] is True and "did not parse" in src["fetch_problem"]
    assert (tmp_path / "skyrimvr" / "meta.json").read_bytes() == meta


def test_a_malformed_commit_id_is_refused():
    net = Net(ml_commit="../../x")
    with pytest.raises(ValueError, match="malformed commit"):
        loot_advisor.newest_branch("skyrimvr", (0, 21), net)


def test_an_oversized_download_is_refused(monkeypatch):
    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self, n=-1):
            return b"x" * (n if n > 0 else loot_advisor.MAX_DOWNLOAD + 1)
    monkeypatch.setattr(loot_advisor.urllib.request, "urlopen", lambda req, timeout=0: Resp())
    with pytest.raises(ValueError, match="refused"):
        loot_advisor._get("https://example.invalid/x")


def test_a_say_message_alone_exits_0(monkeypatch, capsys, install, tmp_path):
    game, local, names = install
    fake = FakeLoot(names, {"Skyrim.esm", "A.esp", "B.esp"}, ["Skyrim.esm", "A.esp", "B.esp"],
                    general=[Msg("say", "just a note")])
    monkeypatch.setattr(loot_advisor.skyrim_paths, "game_root", lambda: (game, "test"))
    monkeypatch.setattr(loot_advisor, "_plugin_check", lambda: types.SimpleNamespace(
        mo2_folders=lambda env: ([], None), locate=lambda n, d, f: str(game / "Data" / n)))
    monkeypatch.setattr(loot_advisor.libloot_loader, "load", lambda: fake)
    monkeypatch.setattr(loot_advisor, "CACHE", tmp_path / "cache")
    monkeypatch.setattr(loot_advisor, "_get", lambda url, timeout=20.0: Net()(url))
    assert loot_advisor.main(["--plugins-txt", str(local / "Plugins.txt")]) == 0
    assert "just a note" in capsys.readouterr().out


def test_python_bytecode_in_the_unpacked_copy_is_refused_and_none_is_written(tmp_path, fresh_import):
    """Confirmation review: a planted __pycache__ .pyc would be imported in place of the checked source."""
    make_wheel(tmp_path / "built")
    kw = dict(shipped=tmp_path / "none", built=tmp_path / "built", cache=tmp_path / "cache")
    libloot_loader.load(**kw)
    [extracted] = [p for p in (tmp_path / "cache").iterdir() if p.is_dir()]
    assert not list(extracted.rglob("__pycache__")), "the loader wrote bytecode into the checked copy"
    sys.modules.pop("loot", None)
    (extracted / "loot" / "__pycache__").mkdir()
    (extracted / "loot" / "__pycache__" / "__init__.cpython-310.pyc").write_bytes(b"planted")
    with pytest.raises(libloot_loader.Unavailable, match="does not"):
        libloot_loader.load(**kw)


def test_locked_plugin_returns_to_its_index_after_the_sort():
    order = ['Skyrim.esm', 'Update.esm', 'A.esp', 'B.esp', 'Locked.esp', 'C.esp']
    assert loot_advisor.apply_locks(order, [('Locked.esp', 2)]) == ['Skyrim.esm', 'Update.esm', 'Locked.esp', 'A.esp', 'B.esp', 'C.esp']


def test_locks_apply_lowest_index_first_and_ignore_case_and_absent_plugins():
    order = ['a.esp', 'b.esp', 'X.esp', 'Y.esp', 'c.esp']
    out = loot_advisor.apply_locks(order, [('y.ESP', 0), ('x.esp', 4), ('Gone.esp', 1)])
    assert out == ['Y.esp', 'a.esp', 'b.esp', 'c.esp', 'X.esp']


def test_lock_index_past_the_end_goes_last():
    assert loot_advisor.apply_locks(['a.esp', 'L.esp', 'b.esp'], [('L.esp', 99)]) == ['a.esp', 'b.esp', 'L.esp']


def test_read_locks_parses_mo2_format(tmp_path):
    f = tmp_path / 'lockedorder.txt'
    f.write_bytes(b'# This file was automatically generated by Mod Organizer.\r\nUHDAP - MusicHQ.esp|80\r\n')
    assert loot_advisor.read_locks(f) == [('UHDAP - MusicHQ.esp', 80)]
    assert loot_advisor.read_locks(tmp_path / 'missing.txt') == []


def test_render_keeps_plugins_txt_lines_crlf_and_omits_implicit_plugins():
    order = ['Skyrim.esm', 'ccA.esl', 'b.esp', 'A.esp']
    lo, pl = loot_advisor.render(order, ['*A.esp', '*b.esp'])
    assert lo == loot_advisor.HEADER + '\r\nSkyrim.esm\r\nccA.esl\r\nb.esp\r\nA.esp\r\n'
    assert pl == loot_advisor.HEADER + '\r\n*b.esp\r\n*A.esp\r\n'


def test_render_refuses_a_plugins_txt_entry_the_sort_lost():
    with pytest.raises(ValueError):
        loot_advisor.render(['Skyrim.esm'], ['*Lost.esp'])


def _app_fixture(tmp_path, userlist=False, game_folder='Skyrim Special Edition'):
    app = tmp_path / 'app'
    game = app / 'games' / game_folder
    game.mkdir(parents=True)
    (app / 'prelude').mkdir()
    (game / 'masterlist.yaml').write_text('plugins: []\n')
    (app / 'prelude' / 'prelude.yaml').write_text('plugins: []\n')
    if userlist:
        (game / 'userlist.yaml').write_text('plugins: []\n')
    return app


@pytest.mark.parametrize('has_userlist', [False, True])
def test_app_userlist_is_optional(tmp_path, monkeypatch, has_userlist):
    app = _app_fixture(tmp_path, has_userlist)
    game = tmp_path / 'game'
    (game / 'Data').mkdir(parents=True)
    (game / 'SkyrimSE.exe').touch()
    profile = tmp_path / 'profile'
    profile.mkdir()
    (profile / 'plugins.txt').write_text('*A.esp\n')
    (profile / 'modlist.txt').write_text('')
    fake = FakeLoot(['A.esp'], {'A.esp'}, ['A.esp'])
    monkeypatch.setattr(loot_advisor.skyrim_paths, 'game_root', lambda: (game, 'test'))
    monkeypatch.setattr(libloot_loader, 'load', lambda: fake)
    monkeypatch.setattr(loot_advisor, '_plugin_check', lambda: types.SimpleNamespace(
        mo2_folders=lambda env: ([], None), locate=lambda n, d, f: game / 'Data' / n))
    _, proposed, _, info = loot_advisor.sort_profile(profile, app, tmp_path / 'out')
    assert proposed == ['A.esp']
    assert bool(info['userlist']) == has_userlist
    assert hasattr(fake, 'userlist') == has_userlist


def test_propose_rejects_vr_before_writing(tmp_path, monkeypatch):
    game = tmp_path / 'vr'
    game.mkdir()
    (game / 'SkyrimVR.exe').touch()
    monkeypatch.setattr(loot_advisor.skyrim_paths, 'game_root', lambda: (game, 'test'))
    with pytest.raises(ValueError, match='SE/AE only'):
        loot_advisor.sort_profile(tmp_path, tmp_path, tmp_path / 'out')
    assert not (tmp_path / 'out').exists()


def test_proposal_render_error_is_clear_outside_main(tmp_path, monkeypatch):
    profile = tmp_path / 'profile'
    profile.mkdir()
    (profile / 'plugins.txt').write_text('*Lost.esp\n')
    monkeypatch.setattr(loot_advisor, 'sort_profile', lambda *a: ([], [], loot_advisor.moves, {}))
    with pytest.raises(ValueError, match='could not render proposal:.*lost.esp'):
        loot_advisor.propose(profile, tmp_path, tmp_path / 'out')
    assert not (tmp_path / 'out' / 'plugins.txt').exists()


def test_app_default_requires_configuration_not_a_user_path(tmp_path, monkeypatch):
    monkeypatch.delenv('LOOT_APP_DIR', raising=False)
    monkeypatch.setattr(loot_advisor.skyrim_paths, 'TOOLKIT_ROOT', tmp_path)
    with pytest.raises(ValueError, match='set LOOT_APP_DIR'):
        loot_advisor.app_dir('')
    monkeypatch.setenv('LOOT_APP_DIR', str(tmp_path / 'configured'))
    assert loot_advisor.app_dir('') == tmp_path / 'configured'


def test_app_default_reads_literal_setting(tmp_path, monkeypatch):
    monkeypatch.delenv('LOOT_APP_DIR', raising=False)
    monkeypatch.setattr(loot_advisor.skyrim_paths, 'TOOLKIT_ROOT', tmp_path)
    (tmp_path / 'skyrim-paths.env').write_text('LOOT_APP_DIR="/configured/app"\n')
    assert loot_advisor.app_dir('') == Path('/configured/app')
    source = (REPO / 'tools/loot_advisor.py').read_text()
    assert 'Path.home()' not in source
    assert '/Users/' not in source and '/Volumes/' not in source


def test_missing_app_file_names_current_option(tmp_path):
    with pytest.raises(ValueError, match='--from-app DIR') as exc:
        loot_advisor.app_files(tmp_path, 'SkyrimSE')
    assert '--loot-dir' not in str(exc.value)


def test_no_flag_cli_has_fixed_output(install, tmp_path, monkeypatch, capsys):
    game, local, names = install
    fake = FakeLoot(names, {'Skyrim.esm', 'A.esp', 'B.esp'}, ['Skyrim.esm', 'B.esp', 'A.esp'])
    monkeypatch.setattr(loot_advisor.skyrim_paths, 'game_root', lambda: (game, 'test'))
    monkeypatch.setattr(loot_advisor.sg_paths, 'plugins_txt', lambda *a: str(local / 'Plugins.txt'))
    monkeypatch.setattr(loot_advisor, '_plugin_check', lambda: types.SimpleNamespace(
        mo2_folders=lambda env: ([], None), locate=lambda n, d, f: d / n))
    monkeypatch.setattr(libloot_loader, 'load', lambda: fake)
    monkeypatch.setattr(loot_advisor, 'CACHE', tmp_path / 'cache')
    monkeypatch.setattr(loot_advisor, '_get', Net())
    assert loot_advisor.main([]) == 1
    captured = capsys.readouterr()
    assert captured.err == ''
    assert captured.out == (
        'LOOT 0.29.7 on 3 active plugins; masterlist skyrimvr v0.21@' + 'a' * 7 + '\n'
        "no userlist: rules set in LOOT's app are not applied (--userlist PATH)\n"
        '1 plugin(s) LOOT would move; 0 issue(s)\n'
        '  move   B.esp -> after Skyrim.esm\n' +
        'Advisory only: nothing was reordered. Wrye Bash / the mod manager owns the order; on a kept save '
        'read KNOWLEDGEBASE.local.md `## My preferences` before moving anything.\n')


@pytest.fixture
def proposal_case(tmp_path, monkeypatch):
    game = tmp_path / 'game'
    (game / 'Data').mkdir(parents=True)
    (game / 'SkyrimSE.exe').touch()
    profile = tmp_path / "profile with 'space"
    profile.mkdir()
    mods = tmp_path / 'mods'
    (mods / 'Enabled').mkdir(parents=True)
    (mods / 'Enabled' / 'A.esp').write_bytes(b'TES4')
    (mods / 'Enabled' / 'B.esp').write_bytes(b'TES4')
    (profile / 'modlist.txt').write_text('+Enabled\n')
    lo, pl = loot_advisor.render(['A.esp', 'B.esp'], ['*A.esp', '*B.esp'])
    (profile / 'plugins.txt').write_bytes(pl.encode())
    (profile / 'loadorder.txt').write_bytes(lo.encode())
    (profile / 'lockedorder.txt').write_text('Unknown.esp|0\n')
    monkeypatch.setattr(loot_advisor.skyrim_paths, 'game_root', lambda: (game, 'test'))
    pc = loot_advisor._plugin_check()
    monkeypatch.setattr(pc.skyrim_paths, 'TOOLKIT_ROOT', tmp_path)
    monkeypatch.setattr(loot_advisor, '_plugin_check', lambda: pc)
    monkeypatch.setenv('SKYRIM_MO2_MODS', str(mods))
    monkeypatch.setenv('SKYRIM_MO2_OVERWRITE', '')
    # The explicit --plugins-txt profile must replace this unrelated configured profile.
    monkeypatch.setenv('SKYRIM_LOADORDER_DIR', str(tmp_path / 'wrong profile'))
    fake = FakeLoot(['A.esp', 'B.esp'], {'A.esp', 'B.esp'}, ['B.esp', 'A.esp'])
    monkeypatch.setattr(libloot_loader, 'load', lambda: fake)
    app = _app_fixture(tmp_path)
    return profile, app, tmp_path / 'proposal with space', fake


@pytest.mark.parametrize('identical', [False, True])
def test_propose_end_to_end(proposal_case, capsys, identical):
    import shlex
    profile, app, out, fake = proposal_case
    if identical:
        fake.Game.sort_plugins = lambda self, plugins: list(plugins)
    before = {p: p.read_bytes() for p in profile.iterdir()}
    assert loot_advisor.main(['--from-app', str(app), '--propose', str(out),
                              '--plugins-txt', str(profile / 'plugins.txt')]) == (0 if identical else 1)
    captured = capsys.readouterr()
    assert captured.err == ''
    assert fake.extra[0].name == 'Enabled'
    assert {p: p.read_bytes() for p in profile.iterdir()} == before
    expected = ''.join(f'{hashlib.sha256(before[profile / n]).hexdigest()}  {profile / n}\n'
                       for n in ('plugins.txt', 'loadorder.txt', 'lockedorder.txt'))
    assert (out / 'inputs.sha256').read_text() == expected
    assert (out / 'plugins.txt').read_bytes().endswith(b'*A.esp\r\n' if not identical else b'*B.esp\r\n')
    if identical:
        assert 'Nothing to apply.' in captured.out
    else:
        command = next(l[2:] for l in captured.out.splitlines() if l.startswith('! '))
        assert command.startswith('if pgrep -f ModOrganizer >/dev/null; then')
        assert "echo 'Close MO2 before applying' >&2" in command
        assert 'shasum -a 256 -c ' + shlex.quote(str(out / 'inputs.sha256')) in command
        assert 'cp ' + shlex.quote(str(profile / 'plugins.txt')) + ' ' in command
        assert shlex.quote(str(out / 'plugins.txt')) in command
        assert subprocess.run(['bash', '-n', '-c', command], capture_output=True).returncode == 0


@pytest.mark.parametrize('flag', ['--data', '--userlist', '--json', '--offline'])
def test_propose_rejects_conflicting_options(proposal_case, capsys, flag):
    profile, app, out, _ = proposal_case
    args = ['--from-app', str(app), '--propose', str(out), flag]
    if flag in ('--data', '--userlist'):
        args.append('unused')
    assert loot_advisor.main(args) == 2
    assert flag in capsys.readouterr().err
    assert not out.exists()


def test_from_app_rejects_offline(proposal_case, capsys):
    _, app, _, _ = proposal_case
    assert loot_advisor.main(['--from-app', str(app), '--offline']) == 2
    assert '--offline cannot be combined' in capsys.readouterr().err


def test_app_advice_labels_hash_as_sha256(install, tmp_path, monkeypatch, capsys):
    game, local, names = install
    app = _app_fixture(tmp_path, game_folder='Skyrim VR')
    fake = FakeLoot(names, {'Skyrim.esm', 'A.esp', 'B.esp'}, ['Skyrim.esm', 'A.esp', 'B.esp'])
    monkeypatch.setattr(loot_advisor.skyrim_paths, 'game_root', lambda: (game, 'test'))
    monkeypatch.setattr(loot_advisor, '_plugin_check', lambda: types.SimpleNamespace(
        mo2_folders=lambda env: ([], None), locate=lambda n, d, f: d / n))
    monkeypatch.setattr(libloot_loader, 'load', lambda: fake)
    assert loot_advisor.main(['--from-app', str(app), '--plugins-txt', str(local / 'Plugins.txt')]) == 0
    digest = hashlib.sha256((app / 'games' / 'Skyrim VR' / 'masterlist.yaml').read_bytes()).hexdigest()
    assert 'masterlist local app sha256:' + digest[:7] in capsys.readouterr().out


def test_propose_refuses_output_inside_profile(proposal_case, capsys):
    profile, app, _, _ = proposal_case
    assert loot_advisor.main(['--from-app', str(app), '--propose', str(profile / 'out'),
                              '--plugins-txt', str(profile / 'plugins.txt')]) == 2
    assert 'output must be outside the profile' in capsys.readouterr().err
    assert not (profile / 'out').exists()


def test_propose_requires_mo2(tmp_path, monkeypatch, capsys):
    game = tmp_path / 'game'
    game.mkdir()
    (game / 'SkyrimSE.exe').touch()
    profile = tmp_path / 'stock profile'
    profile.mkdir()
    (profile / 'plugins.txt').write_text('*A.esp\n')
    monkeypatch.setattr(loot_advisor.skyrim_paths, 'game_root', lambda: (game, 'test'))
    monkeypatch.setattr(loot_advisor, '_plugin_check', lambda: types.SimpleNamespace(mo2_folders=lambda e: ([], None)))
    assert loot_advisor.propose(profile, tmp_path, tmp_path / 'out') == 2
    assert '--propose requires an MO2 profile' in capsys.readouterr().err
    assert not (tmp_path / 'out' / 'libloot-input').exists()


def test_propose_without_loadorder_has_no_missing_backup(proposal_case, tmp_path, capsys):
    import shlex
    original, app, out, _ = proposal_case
    profile = tmp_path / 'no loadorder'
    profile.mkdir()
    for name in ('plugins.txt', 'modlist.txt'):
        (profile / name).write_bytes((original / name).read_bytes())
    assert loot_advisor.main(['--from-app', str(app), '--propose', str(out),
                              '--plugins-txt', str(profile / 'plugins.txt')]) == 1
    command = next(l for l in capsys.readouterr().out.splitlines() if l.startswith('! '))
    assert 'cp ' + shlex.quote(str(profile / 'loadorder.txt')) not in command
    assert 'loadorder.txt.bak-' not in command
    assert (out / 'inputs.sha256').read_text().count('\n') == 1


def test_propose_unexpected_exception_is_sort_failure(proposal_case, monkeypatch, capsys):
    profile, app, out, _ = proposal_case
    def fail(*args):
        raise RuntimeError('unexpected')
    monkeypatch.setattr(loot_advisor, 'propose', fail)
    assert loot_advisor.main(['--from-app', str(app), '--propose', str(out),
                              '--plugins-txt', str(profile / 'plugins.txt')]) == 2
    assert 'COULD NOT SORT: libloot: RuntimeError: unexpected' in capsys.readouterr().err


def test_real_libloot_tiny_sort(tmp_path):
    try:
        loot = libloot_loader.load()
    except libloot_loader.Unavailable as exc:
        pytest.skip(str(exc))
    game = tmp_path / 'game'
    data = game / 'Data'
    data.mkdir(parents=True)
    local = tmp_path / 'local'
    local.mkdir()
    def plugin(name, masters=(), flags=0):
        body = b'HEDR' + struct.pack('<HfII', 12, 1.7, 0, 2048)
        for master in masters:
            value = master.encode() + b'\0'
            body += b'MAST' + struct.pack('<H', len(value)) + value + b'DATA\x08\x00' + b'\0' * 8
        path = data / name
        path.write_bytes(b'TES4' + struct.pack('<II', len(body), flags) + b'\0' * 12 + body)
        return path
    paths = [plugin('Skyrim.esm', flags=1), plugin('A.esp', ['Skyrim.esm']), plugin('B.esp', ['Skyrim.esm'])]
    (local / 'Plugins.txt').write_text('*B.esp\n*A.esp\n')
    app = _app_fixture(tmp_path)
    ml, pre, _ = loot_advisor.app_files(app, 'SkyrimSE')
    ml.write_text('plugins:\n  - name: B.esp\n    after: [A.esp]\n')
    g = loot.Game(loot.GameType.SkyrimSE, game, local)
    g.load_current_load_order_state()
    g.load_plugins(paths)
    g.database().load_masterlist_with_prelude(ml, pre)
    assert list(g.sort_plugins(['Skyrim.esm', 'B.esp', 'A.esp'])) == ['Skyrim.esm', 'A.esp', 'B.esp']
