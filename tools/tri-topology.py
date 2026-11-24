#!/usr/bin/env python3
"""tri-topology -- does a FaceGen .tri morph file fit the mesh it morphs? READ-ONLY, stdlib only.

A FaceGen .tri (the race, chargen and expression morphs of a head or head part) holds its own copy of the mesh: a
vertex list and triangles by vertex index. Its morphs are per-vertex offsets, so they fit only a mesh with the same
vertex count in the same vertex order. This compares, for each skinned shape in each SSE NIF given:
  vertices   the .tri's base vertex count vs the shape's (NiSkinPartition vertex data)
  triangles  the .tri's triangles vs the shape's, as unordered vertex-index triples (winding, order and duplicates
             ignored); the triangle set is the evidence for vertex ORDER, which the counts alone cannot show
Verdict per shape:
  match             same vertex count, same triangle set
  vertex-count      the counts differ: the morphs cannot fit this mesh (a .tri of a few vertices is a stub)
  triangles-differ  same count, some triangles differ: a few percent is usually a retriangulation (edge flips; the
                    morphs still address the right vertices); a large share means the vertex order differs

It parses the bytes itself (no PyNifly, which needs a Windows DLL), so it reads only what it needs: SSE NIFs
(BSVersion 100) whose shape is a skinned BSTriShape / BSDynamicTriShape, and FRTRI003 .tri files. Anything else
is named as unsupported, never reported as a match. This is a topology check, not a NIF validator: a match says
the morphs address the right vertices, nothing about whether the NIF is engine-valid (skill skyrim-nif, gates).

Usage:  python tools/tri-topology.py FILE.tri MESH.nif [MESH.nif ...] [--shape NAME] [--json]
Exit:   0 every checked shape matches · 1 a shape does not (listed) · 2 nothing matched and something could not be
        checked (named), never "clean"
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import struct
import sys

SHAPES = {"BSTriShape", "BSDynamicTriShape"}
SKINS = {"NiSkinInstance", "BSDismemberSkinInstance"}


class Unsupported(ValueError):
    """A file this reader does not parse; never a silent mismatch or match."""


def read_tri(data: bytes) -> dict:
    if data[:4] == b"PIRT":
        raise Unsupported("a BodySlide / Outfit Studio morph .tri (magic PIRT), not a FaceGen one: not compared")
    if data[:8] != b"FRTRI003":
        raise Unsupported("not a FRTRI003 FaceGen .tri (magic %r)" % data[:8])
    nverts, ntris, nquads = struct.unpack_from("<3i", data, 8)
    nadd, = struct.unpack_from("<i", data, 44)
    start = 64 + 12 * (nverts + nadd)
    end = start + 12 * ntris
    if min(nverts, ntris, nquads, nadd) < 0 or end > len(data):
        raise Unsupported("truncated or corrupt .tri header (%d verts, %d tris, %d added)" % (nverts, ntris, nadd))
    tris = [struct.unpack_from("<3i", data, start + 12 * k) for k in range(ntris)]
    return {"vertices": nverts, "added_vertices": nadd, "quads": nquads, "triangles": {frozenset(t) for t in tris},
            "triangle_count": ntris}


def _blocks(data: bytes):
    """Header strings and (type, start, end) of every block of an SSE NIF."""
    i = data.index(b"\n") + 1
    if not data.startswith(b"Gamebryo File Format, Version 20.2.0.7"):
        raise Unsupported("not a Gamebryo 20.2.0.7 NIF")
    i += 5                                                       # version, endian
    _user, nblocks, bsver = struct.unpack_from("<III", data, i)
    i += 12
    if bsver != 100:
        raise Unsupported("BSVersion %d: only SSE (100) is read; an LE NiTriShape mesh needs PyFFI" % bsver)
    for _ in range(3):                                           # author, process script, export script
        i += 1 + data[i]
    ntypes, = struct.unpack_from("<H", data, i)
    i += 2
    types = []
    for _ in range(ntypes):
        n, = struct.unpack_from("<I", data, i)
        types.append(data[i + 4:i + 4 + n].decode("latin-1"))
        i += 4 + n
    tidx = struct.unpack_from("<%dH" % nblocks, data, i)
    i += 2 * nblocks
    sizes = struct.unpack_from("<%dI" % nblocks, data, i)
    i += 4 * nblocks
    nstrings, _maxlen = struct.unpack_from("<II", data, i)
    i += 8
    strings = []
    for _ in range(nstrings):
        n, = struct.unpack_from("<I", data, i)
        strings.append(data[i + 4:i + 4 + n].decode("latin-1"))
        i += 4 + n
    ngroups, = struct.unpack_from("<I", data, i)
    i += 4 + 4 * ngroups
    blocks = []
    for b in range(nblocks):
        blocks.append((types[tidx[b] & 0x7FFF], i, i + sizes[b]))
        i += sizes[b]
    nroots, = struct.unpack_from("<I", data, i)                 # footer: root count and root refs
    if i + 4 + 4 * nroots != len(data):
        raise Unsupported("block sizes do not add up to the file size")
    return strings, blocks


def _shape(data: bytes, start: int, strings):
    """(name, skin instance ref) of a BSTriShape: NiObjectNET, NiAVObject (SSE), bounding sphere, then the skin ref."""
    name, nextra = struct.unpack_from("<iI", data, start)
    j = start + 8 + 4 * nextra + 4                               # extra data refs, controller
    j += 4 + 12 + 36 + 4 + 4                                     # flags, translation, rotation, scale, collision
    j += 16                                                      # bounding sphere
    skin, = struct.unpack_from("<i", data, j)
    return (strings[name] if 0 <= name < len(strings) else ""), skin


def _partition(data: bytes, start: int, end: int) -> dict:
    """Vertex count and triangles (global vertex indices, the SSE 'triangles copy') of an SSE NiSkinPartition."""
    nparts, dsize, vsize, _desc = struct.unpack_from("<IIIQ", data, start)
    j = start + 20 + dsize
    tris = set()
    count = 0
    for _ in range(nparts):
        nv, ntri, nbones, nstrips, nw = struct.unpack_from("<5H", data, j)
        j += 10 + 2 * nbones
        if data[j]:
            j += 2 * nv
        j += 1
        if data[j]:
            j += 4 * nv * nw
        j += 1
        if nstrips:
            raise Unsupported("a skin partition stored as strips")
        if data[j]:
            j += 6 * ntri
        j += 1
        if data[j]:
            j += nv * nw
        j += 1 + 2 + 8                                           # bone indices flag, LOD level, vertex desc
        for k in range(ntri):
            tris.add(frozenset(struct.unpack_from("<3H", data, j + 6 * k)))
        j += 6 * ntri
        count += ntri
    if j != end:
        raise Unsupported("NiSkinPartition did not parse to its end (%d of %d bytes)" % (j - start, end - start))
    return {"vertices": dsize // vsize if vsize else None, "triangles": tris, "triangle_count": count}


def read_nif(data: bytes) -> list:
    strings, blocks = _blocks(data)
    out = []
    for btype, start, end in blocks:
        if btype not in SHAPES:
            continue
        name, skin = _shape(data, start, strings)
        entry = {"shape": name, "type": btype}
        if not 0 <= skin < len(blocks) or blocks[skin][0] not in SKINS:
            entry["unsupported"] = "unskinned shape (vertex data inline in the BSTriShape): not read"
        else:
            part, = struct.unpack_from("<i", data, blocks[skin][1] + 4)
            if not 0 <= part < len(blocks) or blocks[part][0] != "NiSkinPartition":
                entry["unsupported"] = "skin instance without a NiSkinPartition"
            else:
                entry.update(_partition(data, blocks[part][1], blocks[part][2]))
        out.append(entry)
    return out


def compare(tri: dict, shape: dict) -> dict:
    if "unsupported" in shape:
        return {"shape": shape["shape"], "status": "unsupported", "reason": shape["unsupported"]}
    mesh, ref = shape["triangles"], tri["triangles"]
    if shape["vertices"] != tri["vertices"]:
        status = "vertex-count"
    else:
        status = "match" if mesh == ref else "triangles-differ"
    return {"shape": shape["shape"], "status": status,
            "vertices": {"tri": tri["vertices"], "mesh": shape["vertices"]},
            "triangles": {"tri": tri["triangle_count"], "mesh": shape["triangle_count"], "shared": len(mesh & ref),
                          "only_in_mesh": len(mesh - ref), "only_in_tri": len(ref - mesh),
                          "differ_percent": round(100.0 * len(mesh - ref) / len(mesh), 1) if mesh else 0.0}}


def check(tri_path: Path, nif_paths, shape=None) -> dict:
    tri = read_tri(Path(tri_path).read_bytes())
    report = {"tri": str(tri_path), "tri_vertices": tri["vertices"], "tri_triangles": tri["triangle_count"],
              "meshes": []}
    for p in nif_paths:
        try:
            shapes = read_nif(Path(p).read_bytes())
        except (Unsupported, struct.error, ValueError, IndexError) as exc:
            report["meshes"].append({"nif": str(p), "error": str(exc) or type(exc).__name__})
            continue
        if shape is not None:
            shapes = [s for s in shapes if s["shape"] == shape]
        report["meshes"].append({"nif": str(p), "shapes": [compare(tri, s) for s in shapes]})
    return report


def verdict(report: dict) -> int:
    results = [s for m in report["meshes"] for s in m.get("shapes", [])]
    if any(s["status"] in ("vertex-count", "triangles-differ") for s in results):
        return 1
    if any("error" in m for m in report["meshes"]) or not any(s["status"] == "match" for s in results):
        return 2
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("tri")
    ap.add_argument("nifs", nargs="+")
    ap.add_argument("--shape", help="check only the shape with this name")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    try:
        report = check(Path(args.tri), [Path(n) for n in args.nifs], args.shape)
    except (OSError, Unsupported, struct.error) as exc:
        print("COULD NOT CHECK: %s -- this is not a clean result." % exc, file=sys.stderr)
        return 2
    code = verdict(report)
    if args.json:
        print(json.dumps(report, indent=1))
    else:
        print("%s: %d vertices, %d triangles" % (report["tri"], report["tri_vertices"], report["tri_triangles"]))
        for m in report["meshes"]:
            if "error" in m:
                print("  %s: COULD NOT CHECK: %s" % (m["nif"], m["error"]))
                continue
            if not m["shapes"]:
                print("  %s: no %s shape%s" % (m["nif"], "/".join(sorted(SHAPES)),
                                                " named " + args.shape if args.shape else ""))
            for s in m["shapes"]:
                if s["status"] == "unsupported":
                    print("  %s [%s]: UNSUPPORTED: %s" % (m["nif"], s["shape"], s["reason"]))
                    continue
                v, t = s["vertices"], s["triangles"]
                print("  %s [%s]: %s  vertices mesh %s / .tri %s  triangles mesh %d / .tri %d (shared %d, only in "
                      "mesh %d = %s%%, only in .tri %d)"
                      % (m["nif"], s["shape"], s["status"].upper(), v["mesh"], v["tri"], t["mesh"], t["tri"],
                         t["shared"], t["only_in_mesh"], t["differ_percent"], t["only_in_tri"]))
        if code == 2:
            print("Nothing was fully checked: this is not a clean result.")
    return code


if __name__ == "__main__":
    sys.exit(main())
