import re

# Comprehensive list of explicit NSFW keywords. 
# Keep it mostly to unambiguous terms to minimize false positives.
NSFW_KEYWORDS = [
    r'\bporn\b', r'\bporno\b', r'\bpornhub\b', r'\bxvideos\b', r'\bxnxx\b', r'\bbrazzers\b',
    r'\bnsfw\b', r'\bonlyfans\b', r'\bfap\b', r'\bhentai\b', r'\bmilf\b', r'\btits\b',
    r'\bdick\b', r'\bcock\b', r'\bpussy\b', r'\bvagina\b', r'\bcum\b', r'\bcumming\b',
    r'\bswallow\b', r'\bbukkake\b', r'\bgangbang\b', r'\bcreampie\b', r'\bblowjob\b', r'\bhandjob\b',
    r'\bincest\b', r'\bstepmom\b', r'\bstepdad\b', r'\bstepsister\b', r'\bstepbro\b',
    r'\bslut\b', r'\bwhore\b', r'\bprostitute\b', r'\bescort\b', r'\bbitch\b', r'\bfuck\b',
    r'\bdildo\b', r'\bvibrator\b', r'\bcamgirl\b', r'\bstripchat\b', r'\bchaturbate\b',
    
    # Cyrillic unambiguous terms
    r'\bпорно\b', r'\bпорнуха\b', r'\bшлюха\b', r'\bхуй\b', r'\bпизда\b', r'\bебать\b',
    r'\bдрочить\b', r'\bминет\b', r'\bкуннилингус\b', r'\bсперма\b', r'\bшлюхи\b', r'\bпроститутка\b',
    r'\bонлифанс\b', r'\bхентай\b',
]

NSFW_DOMAINS = [
    "pornhub.com", "xvideos.com", "xnxx.com", "xhamster.com", "onlyfans.com", "fansly.com",
    "chaturbate.com", "stripchat.com", "livejasmin.com", "brazzers.com", "naughtyamerica.com",
    "rule34.xxx", "e621.net", "gelbooru.com"
]

# Compile the regex pattern once for performance
_NSFW_PATTERN = re.compile(
    '|'.join(NSFW_KEYWORDS), 
    re.IGNORECASE | re.UNICODE
)

def is_nsfw(text: str) -> bool:
    """
    Returns True if the text contains explicit NSFW content or links.
    Used by the App Layer to filter out adult content from feeds and search results.
    """
    if not text:
        return False
        
    text_lower = text.lower()
    
    # 1. Quick domain check
    for domain in NSFW_DOMAINS:
        if domain in text_lower:
            return True
            
    # 2. Regex check for explicit keywords
    if _NSFW_PATTERN.search(text):
        return True
        
    return False
