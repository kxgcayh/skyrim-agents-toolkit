"""tools/master-update-impact.py: what a new master version breaks in the active load order.

Every plugin here is synthetic, built byte by byte with the builders of test_esp_records.py: no game file is read.
"""
from __future__ import annotations

import importlib.util
import struct
import sys

import pytest

from conftest import REPO
from test_esp_records import edid, plugin, rec, sub

sys.path.insert(0, str(REPO / "tools"))
_spec = importlib.util.spec_from_file_location("master_update_impact", REPO / "tools" / "master-update-impact.py")
mui = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mui)

M = "Big.esm"                       # the master being updated; its own records are FormID 01xxxxxx (one master)


def ws(s):
    return struct.pack("<H", len(s)) + s.encode()


def vmad(*scripts):
    """VMAD v5, object format 2: scripts = [(name, [(prop, type, value bytes)])]."""
    out = struct.pack("<hhH", 5, 2, len(scripts))
    for name, props in scripts:
        out += ws(name) + b"\0" + struct.pack("<H", len(props))
        for pname, t, v in props:
            out += ws(pname) + bytes([t, 1]) + v
    return out


def obj(fid):
    return struct.pack("<HhI", 0, -1, fid)


NPC_A = edid("A") + sub("VTCK", struct.pack("<I", 0x01000900))
NPC_A2 = edid("A") + sub("VTCK", struct.pack("<I", 0x01000901))          # 2.x changed the voice
VM_OLD = vmad(("S", [("P1", 1, obj(0x14)), ("P2", 3, struct.pack("<i", 7))]))
VM_REORDERED = vmad(("S", [("P2", 3, struct.pack("<i", 7)), ("P1", 1, obj(0x14))]))
VM_FIXED = vmad(("S", [("P2", 3, struct.pack("<i", 7)), ("P1", 1, obj(0x14)), ("P3", 0, b"")]))


def master(version):
    recs = [rec("NPC_", 0x01000801, NPC_A if version == 1 else NPC_A2),
            rec("ACTI", 0x01000802, edid("Shrine") + sub("VMAD", VM_OLD if version == 1 else VM_REORDERED)),
            rec("QUST", 0x01000803, edid("Q") + sub("VMAD", VM_OLD if version == 1 else VM_FIXED))]
    if version == 1:
        recs.append(rec("GLOB", 0x01000804, edid("Gone")))
    else:
        recs.append(rec("GLOB", 0x01000805, edid("New")))
    return plugin(masters=("Skyrim.esm",), records=recs, flags=1)


@pytest.fixture
def game(tmp_path):
    data = tmp_path / "game" / "Data"
    data.mkdir(parents=True)
    (data / "Skyrim.esm").write_bytes(plugin(masters=(), flags=1))
    (data / "Update.esm").write_bytes(plugin(masters=("Skyrim.esm",), flags=1))
    old, new = tmp_path / "old" / M, data / M
    old.parent.mkdir()
    old.write_bytes(master(1))
    new.write_bytes(master(2))
    return tmp_path / "game", data, old, new


def dep(data, name, records, masters=("Skyrim.esm", M)):
    (data / name).write_bytes(plugin(masters=masters, records=records))


def run(game, lines):
    root, data, old, new = game
    txt = root / "plugins.txt"
    txt.write_text("\n".join(["*" + M] + lines) + "\n", encoding="utf-8")
    return mui.impact(old, new, M, txt, data, root, [])


def kinds(rep, plug):
    d = next(d for d in rep["dependents"] if d["plugin"] == plug)
    return {r["id"]: (r["kind"], r["fields"], r["wins"]) for r in d["rows"]}


def test_vmad_reorder_is_not_a_change_and_an_empty_property_parses():
    assert mui.vmad_canon(VM_OLD) == mui.vmad_canon(VM_REORDERED)
    assert mui.vmad_canon(VM_FIXED) is not None            # type 0: a property with no value
    assert mui.vmad_canon(VM_OLD) != mui.vmad_canon(VM_FIXED)
    assert mui.vmad_canon(b"\x05\x00") is None             # truncated: fall back to bytes, never a guess


def test_master_diff_counts(game):
    from esp_records import read
    removed, added, changed, order_only = mui.master_diff(read(game[2]), read(game[3]))
    assert set(removed) == {0x804} and set(added) == {0x805}
    assert set(changed) == {0x801, 0x803} and order_only == 1      # the shrine was only reordered
    assert changed[0x801][4] == ["VTCK"] and changed[0x803][4] == ["VMAD"]


def test_each_dependent_kind_and_the_winner(game):
    data = game[1]
    dep(data, "Old.esp", [rec("NPC_", 0x01000801, NPC_A), rec("GLOB", 0x01000804, edid("Gone"))])
    dep(data, "Own.esp", [rec("NPC_", 0x01000801, edid("A") + sub("VTCK", struct.pack("<I", 0x00000999)))])
    dep(data, "Cur.esp", [rec("QUST", 0x01000803, edid("Q") + sub("VMAD", VM_FIXED)),
                          rec("ACTI", 0x01000802, edid("Shrine") + sub("VMAD", VM_OLD))])
    dep(data, "Other.esp", [rec("NPC_", 0x00000801, NPC_A)], masters=("Skyrim.esm",))
    rep = run(game, ["*Old.esp", "*Own.esp", "*Cur.esp", "*Other.esp", "Off.esp"])
    assert [d["plugin"] for d in rep["dependents"]] == ["Old.esp", "Own.esp", "Cur.esp"]
    old = kinds(rep, "Old.esp")
    assert old[0x804][0] == "dangling"
    assert old[0x801] == ("keeps-old", [("VTCK", "old")], False)        # Own.esp loads later and wins
    assert kinds(rep, "Own.esp")[0x801] == ("own", [("VTCK", "own")], True)
    cur = kinds(rep, "Cur.esp")
    assert cur == {0x803: ("current", [("VMAD", "new")], True)}          # the reordered shrine is no row at all


def test_a_misaligned_master_list_is_review_not_a_verdict(game):
    dep(game[1], "Shift.esp", [rec("NPC_", 0x02000801, NPC_A)], masters=("Skyrim.esm", "Update.esm", M))
    rep = run(game, ["*Shift.esp"])
    assert kinds(rep, "Shift.esp")[0x801][0] == "review"


def test_the_cli_exit_codes(game, monkeypatch, capsys):
    root, data, old, new = game
    monkeypatch.setattr(mui.plugin_check, "mo2_folders", lambda environ: ([], None))
    monkeypatch.setenv("SKYRIM_GAME_ROOT", str(root))
    txt = root / "plugins.txt"
    txt.write_text("*" + M + "\n", encoding="utf-8")
    assert mui.main([str(old), str(new), "--plugins-txt", str(txt), "--data", str(data)]) == 0
    dep(data, "Old.esp", [rec("NPC_", 0x01000801, NPC_A)])
    txt.write_text("*" + M + "\n*Old.esp\n", encoding="utf-8")
    assert mui.main([str(old), str(new), "--plugins-txt", str(txt), "--data", str(data)]) == 1
    assert "KEEPS-OLD 000801 NPC_ A  VTCK=old" in capsys.readouterr().out
    assert mui.main([str(old), str(root / "nope.esm"), "--plugins-txt", str(txt), "--data", str(data)]) == 2
