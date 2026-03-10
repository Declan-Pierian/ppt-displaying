"""Fast content-similarity engine for presentation reuse.

When a new website is submitted, we compare its crawled content against all
existing website presentations in the database.  If a sufficiently similar
one is found, the generation pipeline can *adapt* the existing slides rather
than creating them from scratch — saving tokens and improving consistency.

The engine is pure Python (Counter + cosine similarity) with zero external
dependencies.  For 100 presentations it runs in ~50-200 ms.
"""

import json
import logging
import math
import re
from collections import Counter

logger = logging.getLogger(__name__)

# Minimum similarity to consider a presentation as a viable adaptation source.
SIMILARITY_THRESHOLD = 0.15

_STOPWORDS = frozenset(
    "the a an is are and or in of to for with on at by from this that it be "
    "as not but we our your their has have had was were will can do does all "
    "so if no up out its also more than just about into over very been would "
    "could should may some any each every these those them then what which who "
    "how when where why because between both through during before after own "
    "only other such here there".split()
)


# ---------------------------------------------------------------------------
# Text extraction
# ---------------------------------------------------------------------------

def extract_text_from_crawled_content(crawled_json: str) -> str:
    """Extract all meaningful text from a stored ``crawled_content`` JSON string.

    Returns a single lowercase string suitable for tokenisation.
    """
    try:
        data = json.loads(crawled_json)
    except (json.JSONDecodeError, TypeError):
        return ""

    parts: list[str] = []

    # Top-level title
    if data.get("title"):
        parts.append(data["title"])

    for slide in data.get("slides", []):
        content = slide.get("content", {})
        if content.get("title"):
            parts.append(content["title"])
        if content.get("meta_description"):
            parts.append(content["meta_description"])

        for section in content.get("sections", []):
            if section.get("heading"):
                parts.append(section["heading"])
            parts.extend(section.get("content", []))

        parts.extend(content.get("key_paragraphs", []))
        parts.extend(content.get("cards", []))
        parts.extend(content.get("list_items", []))
        parts.extend(content.get("hero_text", []))

        for img in content.get("images", []):
            if img.get("name"):
                parts.append(img["name"])
            if img.get("role"):
                parts.append(img["role"])

    return " ".join(filter(None, parts)).lower()


# ---------------------------------------------------------------------------
# Term-frequency & cosine similarity
# ---------------------------------------------------------------------------

def build_term_frequency(text: str) -> Counter:
    """Tokenise *text* into a term-frequency counter.

    Tokens are lowercased, split on non-alphanumeric boundaries, and filtered
    to remove stopwords and very short tokens.
    """
    tokens = re.split(r"[^a-z0-9]+", text.lower())
    return Counter(
        tok for tok in tokens
        if len(tok) >= 2 and tok not in _STOPWORDS
    )


def cosine_similarity(counter_a: Counter, counter_b: Counter) -> float:
    """Compute cosine similarity between two term-frequency counters."""
    if not counter_a or not counter_b:
        return 0.0

    # Only iterate over the *intersection* for the dot product — tokens
    # absent from one counter contribute zero anyway.
    common = set(counter_a) & set(counter_b)
    if not common:
        return 0.0

    dot = sum(counter_a[k] * counter_b[k] for k in common)
    mag_a = math.sqrt(sum(v * v for v in counter_a.values()))
    mag_b = math.sqrt(sum(v * v for v in counter_b.values()))

    if mag_a == 0.0 or mag_b == 0.0:
        return 0.0
    return dot / (mag_a * mag_b)


# ---------------------------------------------------------------------------
# Database search
# ---------------------------------------------------------------------------

def find_most_similar_presentation(
    new_crawled_content: str,
    db,
    exclude_id: int,
) -> tuple[int, str, float] | None:
    """Search the DB for the most similar existing website presentation.

    Only returns a match if the similarity score meets ``SIMILARITY_THRESHOLD``
    (currently 0.15).  Unrelated presentations are NOT returned — adaptation
    only makes sense when the websites share meaningful content overlap.

    Parameters
    ----------
    new_crawled_content : str
        The ``crawled_content`` JSON string of the new presentation.
    db : sqlalchemy Session
        Active database session.
    exclude_id : int
        Presentation ID to exclude (the one currently being generated).

    Returns
    -------
    (presentation_id, source_url, similarity_score) if a sufficiently similar
    presentation is found, otherwise ``None``.
    """
    from app.models.presentation import Presentation

    # Find all existing website presentations with a webpage.html
    candidates = (
        db.query(Presentation)
        .filter(
            Presentation.source_url.isnot(None),
            Presentation.status == "ready",
            Presentation.id != exclude_id,
        )
        .all()
    )

    if not candidates:
        logger.info("No existing website presentations to adapt from.")
        return None

    # Try similarity-based ranking if we have crawled content to compare
    new_text = extract_text_from_crawled_content(new_crawled_content)
    new_tf = build_term_frequency(new_text) if new_text.strip() else None

    best_id: int | None = None
    best_url: str = ""
    best_score: float = 0.0

    for pres in candidates:
        score = 0.0
        if new_tf and pres.crawled_content:
            try:
                cand_text = extract_text_from_crawled_content(pres.crawled_content)
                if cand_text.strip():
                    cand_tf = build_term_frequency(cand_text)
                    score = cosine_similarity(new_tf, cand_tf)
            except Exception as exc:
                logger.warning(
                    "Similarity check failed for presentation %s: %s",
                    pres.id, exc,
                )

        if score > best_score or best_id is None:
            best_score = score
            best_id = pres.id
            best_url = pres.source_url or ""

    if best_id is not None and best_score >= SIMILARITY_THRESHOLD:
        logger.info(
            "Best match for adaptation: presentation #%d (%s) — similarity %.2f",
            best_id, best_url, best_score,
        )
        return best_id, best_url, best_score

    if best_id is not None:
        logger.info(
            "Best match #%d has similarity %.2f (below threshold %.2f) — skipping adaptation",
            best_id, best_score, SIMILARITY_THRESHOLD,
        )
    return None
