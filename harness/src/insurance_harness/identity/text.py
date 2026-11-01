"""Text folding shared by the attribution rules and their data (S5b-1 Spec §2.1)."""

import unicodedata


def fold(text: str) -> str:
    """NFKC without whitespace or private-use code points (font bullets such as U+F043 carry no
    text, and extraction puts them in front of titles)."""
    return "".join(
        c
        for c in unicodedata.normalize("NFKC", text)
        if not c.isspace() and unicodedata.category(c) != "Co"
    )
