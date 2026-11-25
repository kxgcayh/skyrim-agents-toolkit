#!/usr/bin/env python3
"""List or fetch level-2 sections from the local knowledgebase; stdlib only.

The local knowledgebase is KNOWLEDGEBASE.local.md plus, when it has been split, the topic
files in kb.local/. Both are searched by default; --file alone limits the search to one file."""
import argparse
import difflib
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_FILE = ROOT / "KNOWLEDGEBASE.local.md"
DEFAULT_DIR = ROOT / "kb.local"
# The sections a split parent keeps: tools and instructions address them there by name.
PARENT_SECTIONS = ("My preferences", "Index", "Preference details", "Hook Candidates", "Doc index")
INDEX_ROW = re.compile(r"^\|\s*`kb\.local/([^`/\\]+\.md)`\s*\|(.*)$", re.M)
WORD = re.compile(r"[a-z0-9][a-z0-9.+-]{3,}")
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")


def sections(data):
    """Return (line number, heading, original bytes), ignoring fenced headings."""
    starts = []
    offset = 0
    fence = None
    for number, line in enumerate(data.splitlines(keepends=True), 1):
        text = line.decode("utf-8").rstrip("\r\n")
        match = FENCE.match(text)
        if fence:
            if (match and match[1][0] == fence[0]
                    and len(match[1]) >= len(fence) and not match[2].strip()):
                fence = None
        elif match and not (match[1][0] == "`" and "`" in match[2]):
            fence = match[1]
        elif text.startswith("## "):
            starts.append((number, text[3:], offset))
        offset += len(line)
    return [
        (number, heading, data[start:starts[i + 1][2] if i + 1 < len(starts) else len(data)])
        for i, (number, heading, start) in enumerate(starts)
    ]


def check(parent, folder):
    """Drift notes for a split local knowledgebase; [] when it is not split (no topic folder)."""
    if folder is None or not folder.is_dir():
        return []
    entries = sections(parent.read_bytes())
    index = next((body.decode("utf-8") for _, heading, body in entries if heading == "Index"), "")
    rows = {name: rest for name, rest in INDEX_ROW.findall(index)}
    files = sorted(path.name for path in folder.glob("*.md"))
    vocab = {}
    for name in files:
        text = rows.get(name, "") + " " + " ".join(h for _, h, _ in sections((folder / name).read_bytes()))
        vocab[name] = set(WORD.findall(text.casefold()))
    notes = []
    for number, heading, _ in entries:
        if heading in PARENT_SECTIONS:
            continue
        words = set(WORD.findall(heading.casefold()))
        score, best = max(((len(words & vocab[name]), name) for name in files), default=(0, None))
        hint = f"; closest topic file: {folder.name}/{best}" if score else "; no topic file matches, add one with an Index row"
        notes.append(f"{parent.name}:{number} \"{heading}\" belongs in a topic file, not the parent{hint}")
    if "Index" not in [heading for _, heading, _ in entries]:
        notes.append(f"{parent.name} has no ## Index section naming the topic files")
    notes += [f"{folder.name}/{name} has no row in the ## Index table" for name in files if name not in rows]
    notes += [f"{folder.name}/{name} has whitespace in its name, so kb-guard does not snapshot it; rename it"
              for name in files if any(c.isspace() for c in name)]
    notes += [f"## Index names {folder.name}/{name}, which does not exist" for name in sorted(set(rows) - set(files))]
    return notes


def nonnegative(value):
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("must be nonnegative")
    return number


def write(text, stream=None):
    (stream or sys.stdout).buffer.write(text.encode("utf-8"))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path, default=None,
                        help="the parent file (default KNOWLEDGEBASE.local.md); given alone, only it is searched")
    parser.add_argument("--dir", type=Path, default=None,
                        help="folder of topic files searched with the parent (default kb.local/ unless --file is given)")
    parser.add_argument("--max-bytes", type=nonnegative, default=24000,
                        help="section output budget, including prefixes; omission list is extra")
    parser.add_argument("--body", action="store_true",
                        help="list sections containing all words in their bodies, with matching line numbers")
    parser.add_argument("--check", action="store_true",
                        help="report drift in a split knowledgebase (exit 1 when there is any); silent when not split")
    parser.add_argument("words", nargs="*")
    args = parser.parse_args(argv)
    parent = args.file or DEFAULT_FILE
    folder = args.dir if args.dir is not None else (None if args.file else DEFAULT_DIR)
    if args.check:
        try:
            notes = check(parent, folder)
        except (OSError, UnicodeError) as exc:
            write(f"Cannot check {parent}: {exc}\n", sys.stderr)
            return 2
        for note in notes:
            write(note + "\n")
        return 1 if notes else 0
    files = [parent] + (sorted(folder.glob("*.md")) if folder is not None and folder.is_dir() else [])
    multi = len(files) > 1
    entries = []
    total = 0
    for path in files:
        try:
            data = path.read_bytes()
            data.decode("utf-8")
        except (OSError, UnicodeError) as exc:
            write(f"Cannot read {path}: {exc}\n", sys.stderr)
            return 2
        total += len(data)
        label = f"{folder.name}/{path.name}" if path != parent else path.name
        for number, heading, body in sections(data):
            entries.append((f"{label}:{number}" if multi else str(number), heading, body, label, number))
    if not args.words:
        for where, heading, body, *_ in entries:
            write(f"{where}  {len(body)}  {heading}\n")
        write(f"Total: {len(entries)} sections, {total} bytes" + (f" in {len(files)} files" if multi else "") + "\n")
        return 0
    words = [word.casefold() for arg in args.words for word in arg.split()]
    matches = [entry for entry in entries if all(word in entry[1].casefold() for word in words)]
    if args.body or not matches:
        body_matches = []
        for where, heading, body, label, number in entries:
            lines = body.decode("utf-8").splitlines()[1:]
            if all(word in "\n".join(lines).casefold() for word in words):
                hit_lines = [str(number + i) for i, line in enumerate(lines, 1)
                             if any(word in line.casefold() for word in words)]
                body_matches.append((where, heading, len(body), hit_lines))
        if body_matches:
            for where, heading, size, hit_lines in body_matches:
                write(f"{where}  {size}  {heading}  (matching lines: {', '.join(hit_lines)})\n")
            return 0
        if args.body:
            matches = []
    if not matches:
        write("No matching sections. Closest headings:\n")
        query = " ".join(words)
        closest = sorted(entries, key=lambda entry: difflib.SequenceMatcher(
            None, query, entry[1].casefold()).ratio(), reverse=True)[:5]
        for where, heading, body, *_ in closest:
            write(f"{where}  {len(body)}  {heading}\n")
        return 1
    used = 0
    for i, (where, heading, body, label, number) in enumerate(matches):
        prefix = f"{label}:{number}\n".encode("utf-8")
        block = prefix + body + (b"" if body.endswith(b"\n") else b"\n")
        if used + len(block) > args.max_bytes:
            sys.stdout.buffer.write(b"Omitted matched sections (LINE  BYTES  heading):\n")
            for left_where, left_heading, left_body, *_ in matches[i:]:
                sys.stdout.buffer.write(
                    f"{left_where}  {len(left_body)}  {left_heading}\n".encode("utf-8"))
            write(f"Rerun with --max-bytes {used + len(block)} to print it\n")
            break
        sys.stdout.buffer.write(block)
        used += len(block)
    return 0


if __name__ == "__main__":
    sys.exit(main())
