import re
from dataclasses import dataclass
from pathlib import Path

from rank_bm25 import BM25Okapi

_CORPUS_DIR = Path(__file__).parent / "corpus"
_TOKEN_RE = re.compile(r"\w+", re.UNICODE)

# Function words filtered before scoring -- on a corpus this small (a
# few dozen short chunks), BM25's IDF weighting doesn't have enough
# documents to naturally suppress "the", "is", "office", etc., so an
# unrelated question sharing a few common words can outscore a genuine
# but sparsely-worded match. This narrows the gap; it doesn't close it
# -- see docs/ROADMAP.md for the honest limitation.
_STOPWORDS = {
    "en": {
        "a", "an", "the", "is", "are", "was", "were", "be", "been", "to", "of", "in", "on",
        "for", "and", "or", "i", "you", "your", "my", "we", "do", "does", "did", "can", "how",
        "what", "if", "it", "this", "that", "with", "at", "by", "from", "will", "get", "have",
        "has", "need", "me", "not", "no", "so", "as", "who", "when",
    },
    "ar": {
        "من", "إلى", "في", "على", "عن", "مع", "هل", "ما", "هو", "هي", "أنا", "أنت", "لا",
        "نعم", "كيف", "متى", "الذي", "التي", "و", "أو", "كل", "بعد", "قبل",
    },
}

# The only topic whose answer genuinely differs by country in this
# corpus -- everything else (transfer requests, salary certificates, ...)
# is the same policy regardless of which of the four countries asks.
COUNTRY_SPECIFIC_TOPICS = {"annual_leave_policy"}


@dataclass(frozen=True, slots=True)
class Chunk:
    topic: str
    language: str
    section: str
    section_index: int
    text: str


@dataclass(frozen=True, slots=True)
class RetrievalResult:
    chunk: Chunk
    score: float


def _tokenize(text: str, language: str = "en") -> list[str]:
    stopwords = _STOPWORDS.get(language, _STOPWORDS["en"])
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in stopwords]


def _parse_sections(content: str) -> list[tuple[str, str]]:
    """Splits a corpus markdown file on ## headers into (title, body)
    pairs. The leading # title line is not itself a section."""
    sections: list[tuple[str, str]] = []
    current_title: str | None = None
    current_lines: list[str] = []
    for line in content.splitlines():
        if line.startswith("## "):
            if current_title is not None:
                sections.append((current_title, "\n".join(current_lines).strip()))
            current_title = line[3:].strip()
            current_lines = []
        elif line.startswith("# "):
            continue
        else:
            current_lines.append(line)
    if current_title is not None:
        sections.append((current_title, "\n".join(current_lines).strip()))
    return sections


def _load_corpus(corpus_dir: Path) -> list[Chunk]:
    chunks = []
    for path in sorted(corpus_dir.glob("*.md")):
        topic, _, language = path.stem.rpartition(".")
        content = path.read_text(encoding="utf-8")
        index = 0
        for section_title, section_body in _parse_sections(content):
            if section_body:
                chunks.append(
                    Chunk(
                        topic=topic,
                        language=language,
                        section=section_title,
                        section_index=index,
                        text=section_body,
                    )
                )
                index += 1
    return chunks


class KnowledgeStore:
    def __init__(self, corpus_dir: Path = _CORPUS_DIR) -> None:
        self._chunks = _load_corpus(corpus_dir)
        if not self._chunks:
            raise RuntimeError(f"no corpus documents found under {corpus_dir}")
        self._bm25 = BM25Okapi([_tokenize(c.text, c.language) for c in self._chunks])
        # Keyed by position within the topic, not by section title: the
        # English and Arabic corpus files for the same topic use titles
        # that are themselves translated ("What It Is" / "ما هي"), so a
        # title string can never match across languages. Both files are
        # authored with the same sections in the same order, so position
        # is the language-neutral join key.
        self._by_topic_index_language = {
            (c.topic, c.section_index, c.language): c for c in self._chunks
        }

    def get_chunk(self, topic: str, section_index: int, language: str) -> Chunk | None:
        """The same section (by position) in a specific language -- used
        to fetch the parallel-language rendering of a match found in the
        other one."""
        return self._by_topic_index_language.get((topic, section_index, language))

    def search(self, question: str, language: str, top_k: int = 1) -> list[RetrievalResult]:
        scores = self._bm25.get_scores(_tokenize(question, language))
        # Restricted to the requested language explicitly, rather than
        # relying on BM25 to naturally rank same-script chunks higher --
        # lexical overlap across scripts is near zero anyway, but an
        # explicit filter doesn't depend on that holding by accident.
        candidates = [
            (score, chunk)
            for score, chunk in zip(scores, self._chunks, strict=True)
            if chunk.language == language
        ]
        candidates.sort(key=lambda pair: pair[0], reverse=True)
        return [RetrievalResult(chunk=chunk, score=score) for score, chunk in candidates[:top_k]]
