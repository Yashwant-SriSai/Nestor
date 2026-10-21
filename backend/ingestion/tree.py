# tree.py
# A folder tree is the fastest way for a beginner (and the LLM) to see how a
# project is organised. It is built from the files we KEPT, so it never shows
# files we skipped or didn't read.

MAX_TREE_LINES = 400  # keeps the tree small enough to put in a prompt


def build_tree(paths):
    # Turn "a/b.py" into nested dicts: {"a": {"b.py": None}}. None marks a file.
    root = {}
    for path in paths:
        node = root
        parts = path.split("/")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = None

    lines = []

    def walk(node, prefix):
        # Folders first, then files, each alphabetical.
        names = sorted(node, key=lambda n: (node[n] is None, n.lower()))
        for i, name in enumerate(names):
            last = i == len(names) - 1
            is_dir = node[name] is not None
            lines.append(f"{prefix}{'└── ' if last else '├── '}{name}{'/' if is_dir else ''}")
            if is_dir:
                walk(node[name], prefix + ("    " if last else "│   "))

    walk(root, "")

    if len(lines) > MAX_TREE_LINES:
        extra = len(lines) - MAX_TREE_LINES
        lines = lines[:MAX_TREE_LINES] + [f"... ({extra} more lines not shown)"]
    return "\n".join(lines)