# chunker.py
# Search works on small pieces ("chunks") of code, not whole files. Python and
# JavaScript are split with tree-sitter, so each chunk is a whole function or
# class. Every other file type is split into fixed windows of lines.
# Every chunk remembers its file and line numbers, which is what later lets the
# bot CITE exact lines (anti-hallucination guardrail).

import tree_sitter_language_pack as tslp

from backend import config

LANGUAGES = {".py": "python", ".js": "javascript", ".jsx": "javascript",
             ".mjs": "javascript", ".cjs": "javascript"}

_parsers = {}


def _get_parser(lang):
    if lang not in _parsers:
        try:
            _parsers[lang] = tslp.get_parser(lang)
        except Exception:  # noqa: BLE001 - e.g. the parser could not be downloaded
            _parsers[lang] = None  # remember the failure; we fall back to line chunks
    return _parsers[lang]


def _make_chunk(path, lines, start, end):
    """start/end are 0-based row numbers (inclusive). The stored line numbers are 1-based."""
    text = "\n".join(lines[start:end + 1])
    if not text.strip():
        return None
    return {"id": f"{path}:{start + 1}-{end + 1}", "path": path,
            "start_line": start + 1, "end_line": end + 1, "text": text}


def _windows(start, end, size):
    for s in range(start, end + 1, size):
        yield s, min(s + size - 1, end)


def line_chunks(path, text):
    """Fallback for any file type: fixed windows of N lines."""
    lines = text.split("\n")
    chunks = [_make_chunk(path, lines, s, e)
              for s, e in _windows(0, len(lines) - 1, config.FALLBACK_CHUNK_LINES)]
    return [c for c in chunks if c]


def _is_definition(node_type: str) -> bool:
    # Matches function_definition, class_declaration, method_definition, arrow_function ...
    return (any(word in node_type for word in ("function", "class", "method"))
            or node_type in ("decorated_definition", "export_statement"))


def _syntax_chunks(path, text, lang):
    parser = _get_parser(lang)
    if parser is None:
        return None
    tree = parser.parse(text.encode("utf-8"))  # tree-sitter works on bytes
    lines = text.split("\n")

    pieces = []  # (start_row, end_row, is_definition)

    def collect(node):
        start, end = node.start_point.row, node.end_point.row
        if end - start + 1 <= config.CHUNK_MAX_LINES:
            pieces.append((start, end, _is_definition(node.type)))
        elif node.children:
            # Too big (e.g. a long class): look INSIDE it, so we split at method boundaries.
            for child in node.children:
                collect(child)
        else:
            for s, e in _windows(start, end, config.CHUNK_MAX_LINES):
                pieces.append((s, e, False))

    # Start from the root's children (not the root itself), so even small files
    # are split per function.
    for child in tree.root_node.children:
        collect(child)

    # Every function/class becomes its own chunk. Everything else (imports,
    # constants, small statements) is merged together up to the line limit.
    chunks, current = [], None

    def flush():
        if current:
            chunk = _make_chunk(path, lines, current[0], current[1])
            if chunk:
                chunks.append(chunk)

    for start, end, is_def in pieces:
        if is_def:
            flush()
            current = None
            chunk = _make_chunk(path, lines, start, end)
            if chunk:
                chunks.append(chunk)
        elif current is None:
            current = [start, end]
        elif end - current[0] + 1 <= config.CHUNK_MAX_LINES:
            current[1] = max(current[1], end)
        else:
            flush()
            current = [start, end]
    flush()
    return chunks


def chunk_file(path, text):
    name = path.rsplit("/", 1)[-1]
    ext = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
    lang = LANGUAGES.get(ext)
    if lang:
        try:
            chunks = _syntax_chunks(path, text, lang)
            if chunks:
                return chunks
        except Exception:  # noqa: BLE001 - one odd file must never break the whole analysis
            pass
    return line_chunks(path, text)


def chunk_all(files: dict):
    """Chunk every file (most important first). Returns (chunks, hit_limit)."""
    chunks, seen = [], set()
    for path, text in files.items():
        for chunk in chunk_file(path, text):
            if chunk["id"] in seen:
                continue
            if len(chunks) >= config.MAX_CHUNKS:  # resource-limit guardrail
                return chunks, True
            seen.add(chunk["id"])
            chunks.append(chunk)
    return chunks, False