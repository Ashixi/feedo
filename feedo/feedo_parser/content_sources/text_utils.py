import html
import re
import asyncio
import trafilatura


def clean_plain_text(value: str | None) -> str:
    text = html.unescape(value or "")
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def clean_html_text(html_value: str | None) -> str:
    """Prefer `trafilatura` for robust content extraction, fall back to
    a lightweight HTML-stripping fallback when extraction fails.
    """
    if not html_value:
        return ""

    # Try trafilatura directly (the caller should use to_thread if they want it non-blocking)
    try:
        extracted = trafilatura.extract(html_value)
        if extracted:
            return extracted.strip()
    except Exception:
        pass

    # Minimal safe fallback: remove tags and collapse whitespace
    text = html.unescape(html_value)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def sanitize_for_storage(value: str | None) -> str:
    """Sanitize a text blob before storing/indexing.

    This keeps a lightweight set of replacements that are safe and predictable
    for indexing and display, while delegating heavy extraction to
    `trafilatura`.
    """
    if not value:
        return ""

    s = html.unescape(value)
    s = re.sub(
        r'<(?:script|style)[^>]*>[\s\S]*?<\/(?:script|style)>',
        ' ',
        s,
        flags=re.IGNORECASE,
    )
    s = re.sub(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', r'\2 (\1)', s, flags=re.IGNORECASE | re.DOTALL)
    s = re.sub(r'<br\s*/?>', '\n', s, flags=re.IGNORECASE)
    s = re.sub(r'</?(?:p|div|section|article|blockquote|li|ul|ol|h[1-6]|pre|hr)[^>]*>', '\n', s, flags=re.IGNORECASE)
    s = re.sub(r'</?(?:span|strong|b|em|i|u|small|mark|code|kbd|sup|sub|tbody|thead|tr|td|th)[^>]*>', '', s, flags=re.IGNORECASE)
    s = re.sub(r'<[^>]+>', ' ', s)

    s = re.sub(r'\n{3,}', '\n\n', s)
    lines = [re.sub(r'[ \t]+', ' ', line).strip() for line in s.replace('\r\n', '\n').replace('\r', '\n').split('\n')]

    normalized_lines: list[str] = []
    previous_blank = False
    for line in lines:
        if not line:
            if normalized_lines and not previous_blank:
                normalized_lines.append('')
            previous_blank = True
            continue

        normalized_lines.append(line)
        previous_blank = False

    s = '\n'.join(normalized_lines).strip()

    return s


def chunk_long_text(text: str, chunk_size: int = 512, overlap: int = 50) -> list[str]:
    """
    Split a long text into smaller chunks of approximately `chunk_size` characters or words.
    Here we split by paragraphs/lines and build chunks up to a roughly specified character limit,
    with an optional small overlap to preserve context across boundaries.
    """
    if not text:
        return []
    
    # We will chunk by roughly character count for simplicity, aiming for 512-1000 chars.
    # In a production AI setting, this might use a tokenizer (like tiktoken).
    # For now, splitting by paragraphs and combining them up to the chunk_size is safe.
    paragraphs = [p.strip() for p in text.split('\n') if p.strip()]
    
    chunks = []
    current_chunk = []
    current_length = 0
    
    for p in paragraphs:
        if current_length + len(p) > chunk_size and current_chunk:
            # Yield current chunk
            chunks.append(" ".join(current_chunk))
            # Keep the last paragraph as overlap if overlap > 0
            # For simplicity, we just keep the last paragraph if it's not too huge
            if overlap > 0 and len(current_chunk) > 1:
                current_chunk = [current_chunk[-1]]
                current_length = len(current_chunk[0])
            else:
                current_chunk = []
                current_length = 0
        
        # If a single paragraph is bigger than the chunk size, we should split it by sentences/words
        if len(p) > chunk_size * 2:
            # simple word split fallback
            words = p.split(' ')
            sub_chunk = []
            sub_len = 0
            for w in words:
                if sub_len + len(w) > chunk_size and sub_chunk:
                    chunks.append(" ".join(sub_chunk))
                    sub_chunk = []
                    sub_len = 0
                sub_chunk.append(w)
                sub_len += len(w) + 1
            if sub_chunk:
                current_chunk.append(" ".join(sub_chunk))
                current_length += sub_len
        else:
            current_chunk.append(p)
            current_length += len(p) + 1

    if current_chunk:
        chunks.append(" ".join(current_chunk))
        
    return chunks