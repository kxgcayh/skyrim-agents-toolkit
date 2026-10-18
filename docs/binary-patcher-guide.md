# Building a binary patcher (Python + xdelta3) for a plugin that will not load

How to find the bytes, patch an x86_64 SKSE plugin DLL in a length-preserving way, and hand the user a standalone
Python patcher and an `.xdelta` file instead of a modified DLL. Use it when a third-party plugin fails on a newer
game build and either its license forbids shipping a changed DLL (`licensing-and-delta-patching.md`) or you want to
leave the pristine mod folder alone. Why such a plugin fails: `skse-internals.md`.

Tags are those of `macos-crossover.md`. Everything here is **Measured (notes)**: observed on AE 1.7.104 with
SKSE 2.3.1 and carried over from the maintainer's notes, not re-run for this page.

## 1. The approach

1. Locate the machine code or string literal inside the PE32+ (x86_64) DLL.
2. Craft a patch that keeps the byte length, so no relocation, section resize or displacement shifts.
3. Write the patched DLL, then compute an `.xdelta` between the pristine and patched files.
4. Ship a standalone Python patcher that checks, backs up, patches and reports hashes.

## 2. Three patterns that recur with old CommonLibSSE-NG builds

### 2.1 Runtime version check (`Module::load_version`)

Older CommonLibSSE-NG compiles a switch on the game's minor version (`4` = VR, `6` = AE, anything else = SE) into:

```asm
66 83 F8 06       cmp ax, 6      ; minor == 6 ?
0F 95 C0          setne al       ; al = 0 if 6, else 1
FE C0             inc al         ; al = 1 (AE) if 6, else 2 (SE)
```

Minor version `7` (1.7.104) therefore lands on `SE`. Make every minor version of 6 or more evaluate to AE by
changing `setne` to `setb`:

```asm
66 83 F8 06       cmp ax, 6
0F 92 C0          setb al        ; al = 1 only if ax < 6
FE C0             inc al         ; al = 1 (AE) if >= 6, else 2 (SE)
```

| | Bytes |
|---|---|
| Original | `6683f8060f95c0fec0` |
| Patched | `6683f8060f92c0fec0` |

Nine bytes in place; one byte changes (`95` to `92`).

### 2.2 Address Library path template (`IDDatabase::load`)

Older builds read a Format 2 database through a null-terminated format string in `.rdata`:

```
Data/SKSE/Plugins/versionlib-{}.bin\0     (35 bytes)
```

On 1.7.104 the official `versionlib` is Format 5, which those builds cannot read. The community Format 2 file is
`versionl2b-1-7-104-0.bin`. Redirect the template, same length:

```
Data/SKSE/Plugins/versionl2b-{}.bin\0     (35 bytes)
```

### 2.3 The exported version struct (SKSE 2.3.1 gate)

**Symptom.** SKSE 2.3.1 shows `"<Plugin>.dll: must be recompiled for new address library"` before the plugin runs.
The code can be fully patched (2.1, 2.2) and the gate still fires, because it reads the plugin's **exported data
symbol** `SKSEPlugin_Version`, not its code.

**Find the struct by its signature, never by a hardcoded file offset**: dataVersion `01 00 00 00`, the packed
pluginVersion (little-endian), then the plugin name.

```python
SIG = b"\x01\x00\x00\x00\x00\x00\x02\x01QuestJournalOverhaul\x00"   # dataVersion=1, pluginVersion=0x01020000, name
assert data.count(SIG) == 1
struct_off = data.find(SIG)
```

**Patch.** OR the `kVersionIndependentEx_AddressLibraryV5` bit (`1 << 1`) into `versionIndependenceEx`, a single
DWORD edit in place:

```python
ex_off = struct_off + 0x304
assert data[ex_off] in (0x01, 0x03)   # CommonLib's NoStructUse bit is expected to be set already
data[ex_off] |= 0x02                  # add AddressLibraryV5
```

- Idempotent: skip when `data[ex_off] & 0x02` is already set.
- The `+0x304` offset is the struct layout of the CommonLibSSE-NG build of that one DLL (Quest Journal Overhaul).
  Re-check the layout on any other plugin; the full layout is `skse-internals.md` section 7.1
  (not confirmed against an official SKSE header, see its Sources).
- Known-good for `QuestJournalOverhaul.dll`: pristine SHA-256 `7ff0430e...19a1` to fully patched `4a03517d...8770`.

**Limit.** This clears the gate only. QJO still failed inside `SKSE::Init` with a raw SEH exception during the
Address Library load on 1.7.104 under CrossOver, so passing the gate does not make a plugin work. Elimination
analysis and the open hypothesis: `skse-internals.md` section 8.

## 3. Method

### 3.1 Patch in memory

```python
import hashlib

with open("TargetPlugin.dll", "rb") as f:
    data = bytearray(f.read())
orig_sha = hashlib.sha256(data).hexdigest()

pat_orig,  pat_patch  = bytes.fromhex("6683f8060f95c0fec0"), bytes.fromhex("6683f8060f92c0fec0")
path_orig, path_patch = b"Data/SKSE/Plugins/versionlib-{}.bin\x00", b"Data/SKSE/Plugins/versionl2b-{}.bin\x00"

assert data.count(pat_orig) == 1,  "runtime pattern not found exactly once"
assert data.count(path_orig) == 1, "path template not found exactly once"
data = data.replace(pat_orig, pat_patch).replace(path_orig, path_patch)

patched_sha = hashlib.sha256(data).hexdigest()
with open("TargetPlugin-Patched.dll", "wb") as f:
    f.write(data)
```

### 3.2 Generate the delta

```bash
xdelta3 -e -s "TargetPlugin.dll" "TargetPlugin-Patched.dll" "TargetPlugin-1.7.104.xdelta"
```

The result is typically under 300 bytes and holds no copyrighted code or assets.

### 3.3 Verify the round trip

```bash
xdelta3 -d -s "TargetPlugin.dll" "TargetPlugin-1.7.104.xdelta" "VerifiedOutput.dll"
# the SHA-256 of VerifiedOutput.dll must equal patched_sha
```

## 4. What to deliver

```
<ModName> - 1.7.104 Patcher/
  patch_<modname>.py         standalone Python patcher
  <ModName>-1.7.104.xdelta   compact delta
  README.md                  what it changes, how to run it, a SHA-256 table
```

`patch_<modname>.py` must:

1. Write a `.bak` copy of the target DLL before changing anything.
2. Be idempotent: on an already patched DLL, print a message and exit `0`.
3. Log the SHA-256 before and after.
4. Take the DLL path from `sys.argv[1]`, with no hardcoded destructive path.
5. Assert each pattern occurs exactly once, so it refuses a DLL it was not written for.

If a mod manager owns the plugin folder, patch a copy and let the manager deploy it. A patch applied inside a managed
`mods/` folder is overwritten by the next deploy or update, and the toolkit's guards treat MO2's `mods/` as protected.
