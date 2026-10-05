"""Untrusted text goes into a prompt between tags such as <source>...</source>. It must not be able
to close or forge those tags, or to fake the markers a chat template puts between turns."""

import re

# the tags the prompt builders open, and the `<|...|>` and `<<SYS>>` markers of chat templates
_TAG = re.compile(
    r"<(?=/?(?:source|existing_pages|chunk|chunk_notes|section_notes|new_source|sections?|page|question|concept)\b"
    r"|\||<?/?SYS>)",
    re.I,
)
_INST = re.compile(r"\[/?INST\]", re.I)


def fence_safe(text: str) -> str:
    """`text` with look-alike tags and chat markers made inert: the `<` that opens one becomes a
    single angle quote, so `</source>` in a source reads as ‹/source> and ends nothing. Ordinary
    text, including other HTML and `a < b`, is left as it is. This stops a source from forging
    structure; it does not make a model ignore what the source asks."""
    return _INST.sub("(INST)", _TAG.sub("‹", text))
