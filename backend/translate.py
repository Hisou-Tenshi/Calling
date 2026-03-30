"""Translation feature: parse various document formats -> convert to Markdown

-> split into chunks -> translate each chunk -> reassemble.



Key design decisions:

- All formats are first converted to clean Markdown before any splitting or translation.

- Splitting is Markdown-aware: never cuts inside a table, code block, or heading.

- Each LLM call receives ONE logical chunk (paragraph / section / table).

- After LLM-assisted splitting, integrity is verified by checking that all

  original text segments appear in the reconstructed split.

- Chunk size is a SINGLE "target chars per LLM call" parameter (no parent/child confusion).

"""

from __future__ import annotations



import io

import json

import logging

import os

import re

import textwrap

from typing import Any, Callable



logger = logging.getLogger("calling.translate")



# ---------------------------------------------------------------------------

# 1. File -> Markdown conversion

# ---------------------------------------------------------------------------



def _bytes_to_str(raw: bytes) -> str:

    for enc in ("utf-8", "utf-8-sig", "latin-1"):

        try:

            return raw.decode(enc, errors="strict")

        except Exception:

            pass

    return raw.decode("utf-8", errors="ignore")





def _txt_to_md(raw: bytes) -> str:

    return _bytes_to_str(raw)





def _rtf_to_md(raw: bytes) -> str:

    try:

        from striprtf.striprtf import rtf_to_text  # type: ignore

        return rtf_to_text(raw.decode("latin-1", errors="ignore")) or ""

    except ImportError:

        s = raw.decode("latin-1", errors="ignore")

        s = re.sub(r"\\\w+\*?", " ", s)

        s = re.sub(r"[{}]", "", s)

        return s.strip()





def _docx_to_md(raw: bytes) -> str:

    """Convert .docx to Markdown, preserving headings, bold, italic, tables."""

    try:

        from docx import Document  # type: ignore

        from docx.oxml.ns import qn  # type: ignore

    except ImportError:

        raise RuntimeError("python-docx is not installed. Run: pip install python-docx")



    doc = Document(io.BytesIO(raw))

    lines: list[str] = []



    def _run_md(run) -> str:

        t = run.text

        if not t:

            return ""

        # Detect superscript (citation markers)

        is_super = False

        try:

            from docx.oxml.ns import qn as _qn  # type: ignore

            rpr = run._r.find(_qn("w:rPr"))

            if rpr is not None:

                va = rpr.find(_qn("w:vertAlign"))

                if va is not None and va.get(_qn("w:val")) == "superscript":

                    is_super = True

        except Exception:

            pass

        # Also check run.font.superscript if available

        if not is_super:

            try:

                if run.font.superscript:

                    is_super = True

            except Exception:

                pass

        if is_super:

            # Wrap in markdown superscript notation: ^[N]^

            return f"^[{t.strip()}]^"

        if run.bold and run.italic:

            return f"***{t}***"

        if run.bold:

            return f"**{t}**"

        if run.italic:

            return f"*{t}*"

        return t



    def _para_md(para) -> str:

        style_name = (para.style.name or "").lower()

        content = "".join(_run_md(r) for r in para.runs)

        if not content.strip():

            return ""

        if style_name.startswith("heading"):

            try:

                level = int(style_name.split()[-1])

            except ValueError:

                level = 1

            return "#" * min(level, 6) + " " + content

        return content



    def _table_md(table) -> str:

        rows = []

        for row in table.rows:

            cells = [c.text.replace("\n", " ").strip() for c in row.cells]

            rows.append("| " + " | ".join(cells) + " |")

        if not rows:

            return ""

        # Insert separator after header row

        sep = "| " + " | ".join(["---"] * len(table.rows[0].cells)) + " |"

        rows.insert(1, sep)

        return "\n".join(rows)



    # Walk document body in order (paragraphs + tables interleaved)

    from docx.oxml import OxmlElement  # type: ignore  # noqa

    body = doc.element.body

    for child in body:

        tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag

        if tag == "p":

            # Find matching paragraph object

            from docx.text.paragraph import Paragraph  # type: ignore

            para = Paragraph(child, doc)

            md = _para_md(para)

            if md:

                lines.append(md)

            else:

                lines.append("")  # blank line

        elif tag == "tbl":

            from docx.table import Table  # type: ignore

            tbl = Table(child, doc)

            lines.append("")

            lines.append(_table_md(tbl))

            lines.append("")



    # Collapse multiple blank lines

    text = "\n".join(lines)

    text = re.sub(r"\n{3}", "\n\n", text)

    return text.strip()





def _pdf_to_md(raw: bytes) -> str:

    """Extract PDF text with layout awareness; attempt to detect tables."""

    try:

        from pdfminer.high_level import extract_text  # type: ignore

        text = extract_text(io.BytesIO(raw)) or ""

        return _clean_pdf_text(text)

    except ImportError:

        pass

    try:

        import pypdf  # type: ignore

        reader = pypdf.PdfReader(io.BytesIO(raw))

        pages = [page.extract_text() or "" for page in reader.pages]

        return _clean_pdf_text("\n\n".join(pages))

    except ImportError:

        pass

    raise RuntimeError("No PDF library available. Run: pip install pdfminer.six")





# Unicode superscript digit map

_UNICODE_SUPER = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹", "0123456789")





def _normalize_unicode_superscripts(text: str) -> str:

    """

    Convert Unicode superscript digits/sequences to ^[N]^ notation.

    e.g. word¹  -> word^[1]^    word¹² -> word^[12]^

    """

    # Pattern: one or more Unicode superscript digits/chars after non-whitespace

    # Unicode superscripts: ¹²³ and ⁰-⁹

    sup_chars = "⁰¹²³⁴⁵⁶⁷⁸⁹"

    pat = re.compile(r"([" + re.escape(sup_chars) + r"]+)")

    def _repl(m):

        digits = m.group(1).translate(_UNICODE_SUPER)

        return f"^[{digits}]^"

    return pat.sub(_repl, text)






def _protect_inline_citations(text: str) -> str:
    """
    Protect inline citation numbers in PDF-extracted text.
    NOTE: call _normalize_unicode_superscripts() BEFORE this function so
    Unicode superscripts are already in ^[N]^ form.
    Handles:
      - ^[N]^ already normalised  -> left unchanged (negative lookbehind)
      - [1], [2,3], [1-3]         -> ^[1]^, ^[2,3]^, ^[1-3]^
      - (1) after a word char     -> ^[1]^
      - bare numbers glued to punctuation: word.1  word.12,14
    """
    # Already-bracketed [N] but NOT preceded by ^ (avoid re-wrapping ^[N]^)
    text = re.sub(
        r"(?<!\^)\[(\d[\d,\s\-]*)\]",
        lambda m: "^[" + re.sub(r"\s", "", m.group(1)) + "]^",
        text,
    )
    # Parenthesised single numbers after a word char: (1) -> ^[1]^
    text = re.sub(
        r"(?<=\w)\((\d{1,3})\)",
        lambda m: "^[" + m.group(1) + "]^",
        text,
    )
    # Bare numbers glued to end-of-sentence punctuation
    # e.g.  "iPSC.1"  "use,2,3"  "method.12,14"
    # Require: preceded by .!?,;:)  followed by space/capital/eol
    text = re.sub(
        r"(?<=[.!?,;:\)])(\d{1,2}(?:,\d{1,3}){0,4})(?=[\s\u2014\u2013\u201c\u201d\(\[A-Z]|$)",
        lambda m: "^[" + m.group(1) + "]^",
        text,
    )
    return text


def _clean_pdf_text(text: str) -> str:
    """Heuristic cleanup for PDF-extracted text, preserving citation markers."""
    # 1. Normalize Unicode superscript digits first (before any other processing)
    text = _normalize_unicode_superscripts(text)
    # 2. Protect inline citation patterns
    text = _protect_inline_citations(text)
    # 3. Fix hyphenated line breaks
    text = re.sub(r"-\n([a-z])", r"\1", text)
    # 4. Merge lines that are part of the same paragraph
    text = re.sub(r"([^.!?\n])\n([a-z])", r"\1 \2", text)
    # 5. Collapse excessive blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def file_to_markdown(raw: bytes, filename: str) -> str:

    """Convert any supported file to clean Markdown text."""

    ext = os.path.splitext(filename.lower())[1]

    if ext in (".md", ".rmd", ".markdown"):

        return _bytes_to_str(raw)

    if ext in (".txt", ""):

        return _txt_to_md(raw)

    if ext == ".rtf":

        return _rtf_to_md(raw)

    if ext == ".docx":

        return _docx_to_md(raw)

    if ext == ".doc":

        try:

            return _docx_to_md(raw)

        except Exception:

            # Legacy .doc: best-effort text extraction

            text = raw.decode("latin-1", errors="ignore")

            tokens = re.findall(r"[ -~]{4}", text)

            return " ".join(tokens)

    if ext == ".pdf":

        return _pdf_to_md(raw)

    return _txt_to_md(raw)





# Keep old name as alias for compatibility with streaming endpoint

def extract_text(raw: bytes, filename: str) -> str:

    return file_to_markdown(raw, filename)





# ---------------------------------------------------------------------------

# 2. Markdown-aware splitting

# ---------------------------------------------------------------------------



DEFAULT_CHUNK_MAX_CHARS = 2000   # target chars per LLM translate call



# Kept for backward compat with streaming endpoint

DEFAULT_PARENT_MAX_CHARS = DEFAULT_CHUNK_MAX_CHARS

DEFAULT_CHILD_MAX_CHARS  = DEFAULT_CHUNK_MAX_CHARS

DEFAULT_PARENT_SEPS      = ["\n\n", "\n", ". "]



SEPARATOR_PRESETS: dict[str, list[str]] = {

    "paragraph": ["\n\n"],

    "sentence":  ["\n\n", "\n", ". ", "! ", "? "],

    "heading":   ["\n# ", "\n## ", "\n### ", "\n#### ", "\n\n"],

}





def _is_table_line(line: str) -> bool:

    return bool(re.match(r"^\s*\|", line))





def _split_markdown(text: str, max_chars: int) -> list[str]:

    """

    Split Markdown into translate-ready chunks:

    - Never splits inside a fenced code block.

    - Never splits inside a Markdown table.

    - Tries to split on blank lines (paragraph boundaries) first.

    - Falls back to sentence boundaries, then hard-wraps only as a last resort.

    - Each chunk is at most max_chars characters.

    """

    if not text.strip():

        return []

    if len(text) <= max_chars:

        return [text]



    # Tokenise into atomic blocks that must not be split internally

    blocks: list[str] = _tokenise_md_blocks(text)



    chunks: list[str] = []

    current_parts: list[str] = []

    current_len = 0



    def flush():

        nonlocal current_parts, current_len

        if current_parts:

            chunks.append("\n\n".join(current_parts).strip())

            current_parts = []

            current_len = 0



    for block in blocks:

        blen = len(block)

        if blen == 0:

            continue



        if current_len + blen + 2 <= max_chars:

            current_parts.append(block)

            current_len += blen + 2

        else:

            if current_parts:

                flush()

            # Block itself is larger than max_chars: hard-split by sentence then wrap

            if blen > max_chars:

                sub = _hard_split(block, max_chars)

                for i, s in enumerate(sub):

                    if i < len(sub) - 1:

                        chunks.append(s)

                    else:

                        current_parts = [s]

                        current_len = len(s)

            else:

                current_parts = [block]

                current_len = blen



    flush()

    return [c for c in chunks if c.strip()]





def _tokenise_md_blocks(text: str) -> list[str]:

    """

    Tokenise a Markdown document into atomic blocks:

    - Fenced code blocks  (``` ... ```)

    - Table groups (consecutive | lines)

    - Heading lines (# ...)

    - Paragraph groups (blank-line separated)

    """

    lines = text.split("\n")

    blocks: list[str] = []

    i = 0

    n = len(lines)



    while i < n:

        line = lines[i]



        # Fenced code block

        if re.match(r"^```", line):

            j = i + 1

            while j < n and not re.match(r"^```", lines[j]):

                j += 1

            j = min(j, n - 1)

            blocks.append("\n".join(lines[i:j+1]))

            i = j + 1

            continue



        # Table: collect consecutive table lines

        if _is_table_line(line):

            j = i

            while j < n and _is_table_line(lines[j]):

                j += 1

            blocks.append("\n".join(lines[i:j]))

            i = j

            continue



        # Heading

        if re.match(r"^#{1,6} ", line):

            blocks.append(line)

            i += 1

            continue



        # Blank line: separator (skip)

        if not line.strip():

            i += 1

            continue



        # Paragraph: collect until blank line or special block

        j = i

        para_lines = []

        while j < n and lines[j].strip():

            if re.match(r"^```", lines[j]) or _is_table_line(lines[j]) or re.match(r"^#{1,6} ", lines[j]):

                break

            para_lines.append(lines[j])

            j += 1

        blocks.append("\n".join(para_lines))

        i = j



    return [b for b in blocks if b.strip()]





def _hard_split(text: str, max_chars: int) -> list[str]:

    """Last-resort splitter: sentence boundaries then hard wrap."""

    # try sentence split first

    sentences = re.split(r"(?<=[.!?]) +", text)

    chunks: list[str] = []

    cur = ""

    for s in sentences:

        if len(cur) + len(s) + 1 <= max_chars:

            cur = (cur + " " + s).strip()

        else:

            if cur:

                chunks.append(cur)

            if len(s) > max_chars:

                # hard wrap

                chunks.extend(textwrap.wrap(s, width=max_chars, break_long_words=True))

                cur = ""

            else:

                cur = s

    if cur:

        chunks.append(cur)

        return chunks or [text]





# ---------------------------------------------------------------------------

# 3. Chunk integrity verification

# ---------------------------------------------------------------------------



def verify_chunks(original: str, chunks: list[str]) -> dict:

    """

    Verify that the chunks together cover all significant content of the

    original text.  Returns a dict with:

      ok: bool

      coverage: float  (0-1)

      missing_samples: list[str]  (up to 5 samples of missing content)

    """

    if not chunks:

        return {"ok": False, "coverage": 0.0, "missing_samples": ["no chunks"]}



    # Normalise whitespace for comparison

    def _norm(s: str) -> str:

        return re.sub(r"\s+", " ", s).strip()



    combined = _norm(" ".join(chunks))

    orig_norm = _norm(original)



    if not orig_norm:

        return {"ok": True, "coverage": 1.0, "missing_samples": []}



    # Sample the original in 80-char windows every 120 chars

    # and check each sample exists in combined

    samples = []

    step = 120

    win = 80

    for i in range(0, len(orig_norm), step):

        s = orig_norm[i:i+win]

        if len(s) < 20:

            continue

        samples.append(s)



    if not samples:

        return {"ok": True, "coverage": 1.0, "missing_samples": []}



    missing = [s for s in samples if s not in combined]

    coverage = 1.0 - len(missing) / len(samples)

    ok = coverage >= 0.90   # allow up to 10% mismatch (whitespace normalisation artefacts)



    return {

        "ok": ok,

        "coverage": round(coverage, 3),

        "missing_samples": missing[:5],

    }





# ---------------------------------------------------------------------------

# 4. Translation prompt  (Markdown-aware, table-aware)

# ---------------------------------------------------------------------------



TRANSLATE_SYSTEM = (
    "You are a professional translator.\n"
    "Rules:\n"
    "1. Translate the text into {target_lang}{src_clause}.\n"
    "2. Preserve ALL Markdown syntax exactly: headings (#), bold (**), italic (*), "
    "bullet lists (- / *), numbered lists, code blocks (```), inline code (`), "
    "blockquotes (>), and horizontal rules (---).\n"
    "3. For Markdown tables: translate ONLY the cell text. "
    "Keep the pipe characters (|), dashes (---), and column alignment unchanged. "
    "Do NOT add or remove columns or rows.\n"
    "4. Do NOT translate: URLs, file paths, code inside backticks, variable names, "
    "LaTeX math ($ ... $ or $$ ... $$).\n"
    "5. Citation markers in the format ^[N]^ (e.g. ^[1]^, ^[2,3]^, ^[12]^) are "
    "SUPERSCRIPT reference numbers. Copy them VERBATIM at the exact same position. "
    "Do NOT remove, reorder, merge, or reformat them. "
    "Do NOT convert them to plain numbers, footnotes, or any other format.\n"
    "6. Output ONLY the translated text. No explanations, no preamble, no notes."
)



TRANSLATE_USER = "Text to translate:\n\n{text}"





def build_translate_messages(text: str, *, target_lang: str, source_lang: str | None) -> list[dict]:

    src_clause = f" from {source_lang}" if source_lang else ""

    system = TRANSLATE_SYSTEM.format(target_lang=target_lang, src_clause=src_clause)

    return [

        {"role": "system", "content": system},

        {"role": "user",   "content": TRANSLATE_USER.format(text=text)},

    ]





# ---------------------------------------------------------------------------

# 5. Per-chunk LLM translation

# ---------------------------------------------------------------------------



def _call_claude(messages: list[dict], settings, model: str) -> str:

    from anthropic import Anthropic

    clients = []

    if settings.claude_proxy_key and settings.claude_proxy_base_url:

        clients.append(Anthropic(api_key=settings.claude_proxy_key, base_url=settings.claude_proxy_base_url))

    if settings.claude_proxy_key_2 and settings.claude_proxy_base_url_2:

        clients.append(Anthropic(api_key=settings.claude_proxy_key_2, base_url=settings.claude_proxy_base_url_2))

    if settings.claude_api_key:

        clients.append(Anthropic(api_key=settings.claude_api_key))

    if not clients:

        raise RuntimeError("No Claude API key configured.")

    # Claude uses system separately

    system = next((m["content"] for m in messages if m["role"] == "system"), "")

    user_msgs = [m for m in messages if m["role"] != "system"]

    last_err: Exception | None = None

    for client in clients:

        try:

            resp = client.messages.create(

                model=model, max_tokens=8192,

                system=system,

                messages=user_msgs,

            )

            for block in resp.content:

                if getattr(block, "type", None) == "text":

                    return getattr(block, "text", "") or ""

        except Exception as e:

            last_err = e

    raise last_err or RuntimeError("Claude translation failed.")





def _call_gemini(messages: list[dict], settings, model: str) -> str:

    if not settings.gemini_api_key:

        raise RuntimeError("GEMINI_API_KEY is not configured.")

    from google import genai

    from google.genai import types

    client = genai.Client(api_key=settings.gemini_api_key)

    system = next((m["content"] for m in messages if m["role"] == "system"), "")

    user_text = next((m["content"] for m in messages if m["role"] == "user"), "")

    resp = client.models.generate_content(

        model=model,

        contents=user_text,

        config=types.GenerateContentConfig(

            system_instruction=system,

            max_output_tokens=8192,

        ),

    )

    try:

        return resp.text or ""

    except Exception:

        parts = resp.candidates[0].content.parts

        return "".join(getattr(p, "text", "") for p in parts)





def _call_openai_compat(messages: list[dict], settings, model: str) -> str:

    from openai import OpenAI

    base_url = getattr(settings, "grok_base_url", "https://api.x.ai/v1")

    client = OpenAI(api_key=settings.grok_api_key or "", base_url=base_url)

    resp = client.chat.completions.create(

        model=model,

        messages=messages,

        max_tokens=8192,

    )

    return resp.choices[0].message.content or ""





def translate_chunk(

    text: str,

    settings: Any,

    model: str,

    target_lang: str,

    source_lang: str | None = None,

) -> str:

    """Translate a single markdown chunk."""

    if not text.strip():

        return text

    logger.debug("[translate_chunk] model=%s target=%s chars=%d", model, target_lang, len(text))

    messages = build_translate_messages(text, target_lang=target_lang, source_lang=source_lang)

    if model.startswith("claude-"):

        return _call_claude(messages, settings, model)

    if model.startswith("gemini-"):

        return _call_gemini(messages, settings, model)

    return _call_openai_compat(messages, settings, model)





# ---------------------------------------------------------------------------

# 6. LLM-assisted splitting (with integrity check)

# ---------------------------------------------------------------------------



LLM_SPLIT_SYSTEM = (

    "You are a document segmentation assistant.\n"

    "Split the following Markdown document into logical sections suitable for translation.\n"

    "Rules:\n"

    "1. Return ONLY a JSON array of strings. Each string is one section.\n"

    "2. Do NOT modify, translate, or summarise any text.\n"

    "3. Every character of the original must appear in exactly one section.\n"

    "4. Never split inside a table, code block, or heading+paragraph pair.\n"

    "5. Target roughly {target_chars} characters per section."

)





def llm_split_text(

    text: str,

    *,

    call_llm: Callable[[str], str],

    max_chars: int = DEFAULT_CHUNK_MAX_CHARS,

) -> tuple[list[str], dict]:

    """

    Ask an LLM to split the text.  Returns (chunks, integrity_report).

    Falls back to _split_markdown on any failure.

    """

    prompt = LLM_SPLIT_SYSTEM.format(target_chars=max_chars) + "\n\n" + text[:30000]

    raw = call_llm(prompt)

    match = re.search(r"\[.*\]", raw, re.DOTALL)

    if match:

        try:

            parts = json.loads(match.group(0))

            if isinstance(parts, list) and all(isinstance(p, str) for p in parts) and parts:

                integrity = verify_chunks(text, parts)

                if integrity["ok"]:

                    logger.info("[llm_split] OK coverage=%.2f chunks=%d", integrity["coverage"], len(parts))

                    return parts, integrity

                else:

                    logger.warning(

                        "[llm_split] coverage=%.2f < 0.90, falling back. missing=%s",

                        integrity["coverage"], integrity["missing_samples"][:2],

                    )

        except Exception as e:

            logger.warning("[llm_split] JSON parse error: %s", e)



    # Fallback

    fallback = _split_markdown(text, max_chars)

    integrity = verify_chunks(text, fallback)

    return fallback, integrity





# backward compat alias used in streaming endpoint

def split_into_parent_chunks(text, separators=None, max_chars=DEFAULT_CHUNK_MAX_CHARS):

    return _split_markdown(text, max_chars)





def _split_by_separators(text, seps, max_chars):

    """Legacy alias used by streaming endpoint."""

    return _split_markdown(text, max_chars)





# ---------------------------------------------------------------------------





# ---------------------------------------------------------------------------

# 7a. Reference section detection

# ---------------------------------------------------------------------------



# Regex patterns that strongly indicate a reference/bibliography section heading

_REF_HEADING_RE = re.compile(

    r"""(?ix)          # case-insensitive, verbose

    ^\#{1,6}\s*        # Markdown heading marker

    (?:

        references?    # References / Reference

      | bibliography   # Bibliography

      | bibliographie  # French

      | literatur      # German

      | 参考文献         # 参考文献

      | 参考资料         # 参考资料

      | 文献               # 文献

      | cited\s+works

      | works\s+cited

      | sources

      | notes

      | endnotes

      | footnotes

    )

    \s*$

    """,

    re.UNICODE,

)



# Regex for un-headed reference list items (numbered/bracketed citations)

_REF_ITEM_RE = re.compile(

    r"""(?x)

    ^\s*(?:

        \[\d+\]        # [1] style

      | \d+\.\s        # 1. style

      | \(\d+\)        # (1) style

    )

    """,

)



LLM_REF_DETECT_PROMPT = (

    "Does the following text start a References, Bibliography, or Works Cited section "

    "of an academic/technical document? "

    "Answer with exactly one word: YES or NO.\n\nText:\n{text}"

)





def _is_reference_heading_regex(chunk: str) -> bool:

    """Fast regex check: True if the chunk looks like a references section heading."""

    first_line = chunk.strip().split("\n")[0].strip()

    return bool(_REF_HEADING_RE.match(first_line))





def _is_reference_section_llm(

    chunk: str,

    settings: Any,

    model: str,

) -> bool:

    """Ask the LLM whether this chunk is a reference section start."""

    prompt = LLM_REF_DETECT_PROMPT.format(text=chunk[:800])

    try:

        answer = translate_chunk(

            prompt, settings, model,

            target_lang="English",   # not a real translation; just get YES/NO

            source_lang=None,

        ).strip().upper()

        result = answer.startswith("YES")

        logger.info("[ref_detect] LLM answered %r -> is_ref=%s", answer[:20], result)

        return result

    except Exception as e:

        logger.warning("[ref_detect] LLM call failed: %s", e)

        return False





def detect_reference_section(

    chunk: str,

    settings: Any,

    model: str,

    *,

    use_llm: bool = True,

) -> bool:

    """

    Return True if this chunk appears to start a References/Bibliography section.

    Strategy:

      1. Fast regex check (no API cost).

      2. If the chunk starts with any heading and regex did not match, ask the LLM.

    """

    if _is_reference_heading_regex(chunk):

        logger.info("[ref_detect] regex matched reference heading")

        return True



    # Only call LLM when the chunk starts with a heading (to keep cost low)

    first_line = chunk.strip().split("\n")[0].strip()

    if use_llm and re.match(r"^#{1,6} ", first_line):

        return _is_reference_section_llm(chunk, settings, model)



    return False



# 7. High-level orchestrator

# ---------------------------------------------------------------------------



def translate_document(

    raw: bytes,

    filename: str,

    settings: Any,

    model: str,

    target_lang: str,

    source_lang: str | None = None,

    split_mode: str = "separator",

    separator_preset: str = "paragraph",

    custom_separators: list[str] | None = None,

    parent_max_chars: int = DEFAULT_CHUNK_MAX_CHARS,

    child_max_chars: int = DEFAULT_CHUNK_MAX_CHARS,

    llm_split_model: str | None = None,

    progress_cb=None,

) -> dict:

    """

    Full pipeline:

      file bytes -> Markdown -> smart chunks -> translate each -> reassemble.



    progress_cb(done, total, chunk_preview) is called after each chunk.

    Returns dict: translated_text, chunks_total, filename, integrity.

    """

    chunk_max = max(parent_max_chars, child_max_chars, 500)



    # 1. Convert to Markdown

    logger.info("[translate] start file=%s model=%s target=%s split_mode=%s", filename, model, target_lang, split_mode)

    md_text = file_to_markdown(raw, filename)

    logger.info("[translate] converted to MD: %d chars from %s", len(md_text), filename)



    if not md_text.strip():

        return {"translated_text": "", "chunks_total": 0, "filename": filename,

                "error": "Could not extract text from file."}



    # 2. Split

    integrity_report: dict = {}

    if split_mode == "llm":

        split_model = llm_split_model or model

        def _call_llm_for_split(prompt: str) -> str:

            return translate_chunk(prompt, settings, split_model,

                                   target_lang="English", source_lang=None)

        chunks, integrity_report = llm_split_text(

            md_text, call_llm=_call_llm_for_split, max_chars=chunk_max

        )

    else:

        chunks = _split_markdown(md_text, chunk_max)

        integrity_report = verify_chunks(md_text, chunks)



    total = len(chunks)

    logger.info("[translate] %d chunks, integrity=%s", total, integrity_report)



    if not integrity_report.get("ok", True):

        logger.warning("[translate] integrity check failed: coverage=%.2f missing=%s",

                       integrity_report.get("coverage", 0),

                       integrity_report.get("missing_samples", [])[:2])



    # 3. Translate each chunk (skip reference section onwards)

    translated_parts: list[str] = []

    in_references = False

    for i, chunk in enumerate(chunks):

        logger.info("[translate] chunk %d/%d chars=%d", i + 1, total, len(chunk))



        # Check if this chunk starts the reference section

        if not in_references:

            if detect_reference_section(chunk, settings, model):

                in_references = True

                logger.info("[translate] reference section detected at chunk %d/%d", i + 1, total)



        if in_references:

            # Pass reference chunks through verbatim

            translated_parts.append(chunk)

            logger.info("[translate] chunk %d/%d skipped (references)", i + 1, total)

        else:

            t = translate_chunk(chunk, settings, model,

                               target_lang=target_lang, source_lang=source_lang)

            logger.debug("[translate] chunk %d/%d done output=%d chars", i + 1, total, len(t))

            translated_parts.append(t)



        if progress_cb:

            progress_cb(i + 1, total, chunk[:80])



    result_text = "\n\n".join(translated_parts)

    logger.info("[translate] done file=%s total_chunks=%d output_chars=%d",

                filename, total, len(result_text))

    return {

        "translated_text": result_text,

        "chunks_total": total,

        "filename": filename,

        "integrity": integrity_report,

    }

