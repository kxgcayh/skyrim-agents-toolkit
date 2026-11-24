#!/usr/bin/env python3
"""List or fetch level-2 sections from the local knowledgebase; stdlib only."""
import argparse
import difflib
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_FILE = ROOT / "KNOWLEDGEBASE.local.md"
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


def nonnegative(value):
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("must be nonnegative")
    return number


def write(text, stream=None):
    (stream or sys.stdout).buffer.write(text.encode("utf-8"))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path, default=DEFAULT_FILE)
    parser.add_argument("--max-bytes", type=nonnegative, default=24000,
                        help="section output budget, including prefixes; omission list is extra")
    parser.add_argument("--body", action="store_true",
                        help="list sections containing all words in their bodies, with matching line numbers")
    parser.add_argument("words", nargs="*")
    args = parser.parse_args(argv)
    try:
        data = args.file.read_bytes()
        data.decode("utf-8")
    except (OSError, UnicodeError) as exc:
        write(f"Cannot read {args.file}: {exc}\n", sys.stderr)
        return 2
    entries = sections(data)
    if not args.words:
        for number, heading, body in entries:
            write(f"{number}  {len(body)}  {heading}\n")
        write(f"Total: {len(entries)} sections, {len(data)} bytes\n")
        return 0
    words = [word.casefold() for arg in args.words for word in arg.split()]
    matches = [entry for entry in entries if all(word in entry[1].casefold() for word in words)]
    if args.body or not matches:
        body_matches = []
        for number, heading, body in entries:
            lines = body.decode("utf-8").splitlines()[1:]
            if all(word in "\n".join(lines).casefold() for word in words):
                hit_lines = [str(number + i) for i, line in enumerate(lines, 1)
                             if any(word in line.casefold() for word in words)]
                body_matches.append((number, heading, len(body), hit_lines))
        if body_matches:
            for number, heading, size, hit_lines in body_matches:
                write(f"{number}  {size}  {heading}  (matching lines: {', '.join(hit_lines)})\n")
            return 0
        if args.body:
            matches = []
    if not matches:
        write("No matching sections. Closest headings:\n")
        query = " ".join(words)
        closest = sorted(entries, key=lambda entry: difflib.SequenceMatcher(
            None, query, entry[1].casefold()).ratio(), reverse=True)[:5]
        for number, heading, body in closest:
            write(f"{number}  {len(body)}  {heading}\n")
        return 1
    used = 0
    for i, (number, heading, body) in enumerate(matches):
        prefix = f"{args.file.name}:{number}\n".encode("utf-8")
        block = prefix + body + (b"" if body.endswith(b"\n") else b"\n")
        if used + len(block) > args.max_bytes:
            sys.stdout.buffer.write(b"Omitted matched sections (LINE  BYTES  heading):\n")
            for left_number, left_heading, left_body in matches[i:]:
                sys.stdout.buffer.write(
                    f"{left_number}  {len(left_body)}  {left_heading}\n".encode("utf-8"))
            write(f"Rerun with --max-bytes {used + len(block)} to print it\n")
            break
        sys.stdout.buffer.write(block)
        used += len(block)
    return 0


if __name__ == "__main__":
    sys.exit(main())
