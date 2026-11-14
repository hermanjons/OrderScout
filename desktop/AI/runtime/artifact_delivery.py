"""Local download links require native delivery receipts, not model strings."""
from pathlib import Path
import hashlib
import html
import os
import re
from urllib.parse import unquote, urlsplit


def artifact_link_token(receipt):
    return hashlib.sha256((receipt["output_path"] + receipt["file_sha256"]).encode("utf-8")).hexdigest()


def verified_file_message_html(message, receipts):
    """Render exact native file references; the model need not format a link.

    All other text stays escaped. This creates no file, approval or new receipt.
    """
    text, spans, linked = str(message or "").strip(), [], {}
    for receipt in receipts:
        token = artifact_link_token(receipt)
        aliases = {receipt["output_path"], receipt["output_path"].replace("\\", "/")}
        for path in aliases:
            # Prefer a complete Markdown link; otherwise link only the exact
            # recorded path, including inline-code/bold wrappers when present.
            markdown = r"\[([^\]\n]+)\]\(\s*<?" + re.escape(path) + r">?\s*\)"
            for match in re.finditer(markdown, text):
                spans.append((match.start(), match.end(), match.group(1), token))
                linked[token] = dict(receipt)
            bare = r"(?<![\w/\\])" + re.escape(path) + r"(?![\w./\\])"
            for match in re.finditer(bare, text):
                if any(start <= match.start() < end for start, end, _, _ in spans):
                    continue
                first, last = match.span()
                for wrapper in ("`", "**"):
                    width = len(wrapper)
                    if first >= width and text[first-width:first] == wrapper and text[last:last+width] == wrapper:
                        first, last = first - width, last + width
                spans.append((first, last, match.group(), token))
                linked[token] = dict(receipt)
    result, position = [], 0
    for first, last, label, token in sorted(spans, key=lambda row: (row[0], -row[1])):
        if first < position:
            continue
        result.extend((html.escape(text[position:first]),
            f'<a href="orderscout://artifact/open/{token}" style="color:#2563EB;">{html.escape(label)}</a>'))
        position = last
    result.append(html.escape(text[position:]))
    return "".join(result).replace("\n", "<br>"), linked


def unverified_local_artifact_links(answer, state):
    from AI.processors.observation_context import verified_export_report_receipts
    allowed = {os.path.normcase(str(Path(row["output_path"]).resolve()))
        for row in verified_export_report_receipts(state) if row.get("output_path")}
    # Literal documentation examples are not file delivery.
    text = re.sub(r"```.*?```|`[^`\n]*`", "", str(answer), flags=re.S)
    problems = []
    for match in re.finditer(r"\[[^\]\n]*\]\(\s*", text):
        start, depth, index = match.end(), 1, match.end()
        if start < len(text) and text[start] == "<":
            end = text.find(">", start + 1)
            target = text[start + 1:end] if end >= 0 else ""
        else:
            while index < len(text) and depth:
                depth += (text[index] == "(") - (text[index] == ")")
                index += 1
            target = text[start:index-1].strip() if depth == 0 else ""
        target = unquote(target)
        # A malformed drive path is still a local delivery claim. Treating
        # D:D%5C... as an unknown URL scheme used to bypass receipt validation.
        local = target.startswith(("sandbox:", "file:", "/", "\\")) or re.match(r"^[A-Za-z]:", target)
        if not local or not re.search(r"\.(?:xlsx?|csv|tsv|pdf|docx?|pptx?|zip|html?)$", target, re.I):
            continue
        path = urlsplit(target).path if target.startswith(("sandbox:", "file:")) else target
        if target.startswith("file:"):
            parts = urlsplit(target)
            if parts.netloc:
                path = "//" + parts.netloc + parts.path
            elif os.name == "nt" and re.match(r"^/[A-Za-z]:/", path):
                path = path[1:]
        if os.path.normcase(str(Path(path).resolve())) not in allowed:
            problems.append(target)
    return problems[:10]
