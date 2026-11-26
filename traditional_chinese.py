"""Normalize all displayed transcripts without an external conversion service."""

from hanziconv import HanziConv


def to_traditional(text: str) -> str:
    # The shared grammatical particle 了 is already valid Traditional Chinese;
    # a character-only dictionary otherwise rewrites it to 瞭 and breaks phrases.
    return "了".join(HanziConv.toTraditional(part) for part in (text or "").split("了"))


def normalize_transcript_payload(value):
    """Keep diagnostic transcript/word fields consistent with the displayed text."""
    if isinstance(value, dict):
        return {
            key: to_traditional(item)
            if key in {"transcript", "word", "punctuated_word"} and isinstance(item, str)
            else normalize_transcript_payload(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [normalize_transcript_payload(item) for item in value]
    return value
