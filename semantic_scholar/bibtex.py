"""BibTeX export functionality for Semantic Scholar papers.

This module provides models and functions for converting paper metadata
to BibTeX format for use in academic writing and citation management.
"""

import re
import unicodedata
from enum import Enum

from pydantic import BaseModel

from .tracking_models import Paper
from .utils.logger import logger


class BibTeXEntryType(str, Enum):
    """BibTeX entry types for different publication types."""

    ARTICLE = "article"
    INPROCEEDINGS = "inproceedings"
    BOOK = "book"
    INCOLLECTION = "incollection"
    PHDTHESIS = "phdthesis"
    MASTERSTHESIS = "mastersthesis"
    TECHREPORT = "techreport"
    MISC = "misc"
    UNPUBLISHED = "unpublished"


class BibTeXFieldConfig(BaseModel):
    """Configuration for which fields to include in BibTeX export."""

    include_abstract: bool = False
    include_url: bool = True
    include_doi: bool = True
    include_keywords: bool = False
    max_authors: int = 0


class BibTeXExportConfig(BaseModel):
    """Configuration for BibTeX export."""

    fields: BibTeXFieldConfig = BibTeXFieldConfig()
    cite_key_format: str = "author_year"


class BibTeXEntry(BaseModel):
    """A single BibTeX entry."""

    entry_type: BibTeXEntryType
    cite_key: str
    fields: dict[str, str]

    def to_bibtex(self) -> str:
        lines = [f"@{self.entry_type.value}{{{self.cite_key},"]
        for key, value in self.fields.items():
            escaped_value = _escape_bibtex(value)
            lines.append(f"  {key} = {{{escaped_value}}},")
        lines.append("}")
        return "\n".join(lines)


def _escape_bibtex(text: str) -> str:
    # Replace backslash with a sentinel first so the braces we introduce as
    # part of \textbackslash{} are not re-escaped by the brace replacements below.
    sentinel = "\x00"
    text = text.replace("\\", sentinel)
    text = text.replace("{", r"\{")
    text = text.replace("}", r"\}")

    other_replacements = [
        ("&", r"\&"),
        ("%", r"\%"),
        ("$", r"\$"),
        ("#", r"\#"),
        ("_", r"\_"),
        ("~", r"\textasciitilde{}"),
        ("^", r"\textasciicircum{}"),
    ]
    for char, replacement in other_replacements:
        text = text.replace(char, replacement)

    text = text.replace(sentinel, r"\textbackslash{}")
    return text


def _normalize_for_cite_key(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    cleaned = re.sub(r"[^a-zA-Z0-9\s]", "", ascii_text)
    return cleaned.replace(" ", "").lower()


def detect_entry_type(paper: Paper) -> BibTeXEntryType:
    publication_types = paper.publicationTypes or []

    type_mapping = {
        "JournalArticle": BibTeXEntryType.ARTICLE,
        "Conference": BibTeXEntryType.INPROCEEDINGS,
        "Book": BibTeXEntryType.BOOK,
        "BookSection": BibTeXEntryType.INCOLLECTION,
        "Review": BibTeXEntryType.ARTICLE,
        "Dataset": BibTeXEntryType.MISC,
        "Patent": BibTeXEntryType.MISC,
    }
    for pub_type in publication_types:
        if pub_type in type_mapping:
            return type_mapping[pub_type]

    venue = (paper.venue or "").lower()
    conference_keywords = [
        "conference", "proceedings", "symposium", "workshop", "icml", "neurips",
        "nips", "iclr", "cvpr", "iccv", "eccv", "acl", "emnlp", "naacl", "aaai", "ijcai",
    ]
    if any(kw in venue for kw in conference_keywords):
        return BibTeXEntryType.INPROCEEDINGS

    journal_keywords = ["journal", "transactions", "letters", "review"]
    if any(kw in venue for kw in journal_keywords):
        return BibTeXEntryType.ARTICLE

    if paper.journal and paper.journal.name:
        return BibTeXEntryType.ARTICLE

    # Any remaining named venue (e.g. "Optics Express", "Physica Scripta")
    # that isn't conference-like is almost always a journal, not misc.
    if venue:
        return BibTeXEntryType.ARTICLE

    return BibTeXEntryType.MISC


def generate_cite_key(paper: Paper, format: str = "author_year") -> str:
    if format == "paper_id":
        return paper.paperId or "unknown"

    author_part = "unknown"
    if paper.authors and len(paper.authors) > 0:
        first_author = paper.authors[0]
        if first_author.name:
            name_parts = first_author.name.split()
            if name_parts:
                author_part = _normalize_for_cite_key(name_parts[-1])

    year_part = str(paper.year) if paper.year else "unknown"

    if format == "author_year":
        return f"{author_part}{year_part}"

    if format == "author_year_title":
        title_part = ""
        if paper.title:
            stop_words = {"a", "an", "the", "on", "in", "of", "for", "to", "and"}
            words = paper.title.split()
            for word in words:
                normalized = _normalize_for_cite_key(word)
                if normalized and normalized.lower() not in stop_words:
                    title_part = normalized[:10]
                    break
        return f"{author_part}{year_part}{title_part}"

    return f"{author_part}{year_part}"


def paper_to_bibtex_entry(
    paper: Paper,
    config: BibTeXExportConfig | None = None,
) -> BibTeXEntry:
    if config is None:
        config = BibTeXExportConfig()

    entry_type = detect_entry_type(paper)
    cite_key = generate_cite_key(paper, config.cite_key_format)

    fields: dict[str, str] = {}

    if paper.title:
        fields["title"] = paper.title

    if paper.authors:
        authors_list = paper.authors
        if config.fields.max_authors > 0:
            authors_list = authors_list[: config.fields.max_authors]
            if len(paper.authors) > config.fields.max_authors:
                author_names = [a.name or "Unknown" for a in authors_list]
                author_names.append("others")
                fields["author"] = " and ".join(author_names)
            else:
                fields["author"] = " and ".join(a.name or "Unknown" for a in authors_list)
        else:
            fields["author"] = " and ".join(a.name or "Unknown" for a in authors_list)

    if paper.year:
        fields["year"] = str(paper.year)

    if entry_type == BibTeXEntryType.INPROCEEDINGS:
        if paper.venue:
            fields["booktitle"] = paper.venue
        elif paper.publicationVenue and paper.publicationVenue.name:
            fields["booktitle"] = paper.publicationVenue.name
    elif entry_type == BibTeXEntryType.ARTICLE:
        if paper.journal and paper.journal.name:
            fields["journal"] = paper.journal.name
            if paper.journal.volume:
                fields["volume"] = paper.journal.volume
            if paper.journal.pages:
                fields["pages"] = paper.journal.pages
        elif paper.venue:
            fields["journal"] = paper.venue

    if config.fields.include_abstract and paper.abstract:
        fields["abstract"] = paper.abstract

    if config.fields.include_doi and paper.externalIds and paper.externalIds.DOI:
        fields["doi"] = paper.externalIds.DOI

    if config.fields.include_url:
        if paper.openAccessPdf and paper.openAccessPdf.url:
            fields["url"] = paper.openAccessPdf.url
        elif paper.externalIds and paper.externalIds.DOI:
            fields["url"] = f"https://doi.org/{paper.externalIds.DOI}"

    if config.fields.include_keywords and paper.fieldsOfStudy:
        fields["keywords"] = ", ".join(paper.fieldsOfStudy)

    entry = BibTeXEntry(entry_type=entry_type, cite_key=cite_key, fields=fields)
    logger.debug("Generated BibTeX entry: %s (type: %s)", cite_key, entry_type.value)
    return entry


def export_papers_to_bibtex(
    papers: list[Paper],
    config: BibTeXExportConfig | None = None,
) -> str:
    if config is None:
        config = BibTeXExportConfig()

    entries: list[str] = []
    seen_keys: set[str] = set()

    for paper in papers:
        entry = paper_to_bibtex_entry(paper, config)

        original_key = entry.cite_key
        counter = 1
        while entry.cite_key in seen_keys:
            if counter <= 26:
                entry.cite_key = f"{original_key}{chr(ord('a') + counter - 1)}"
            else:
                entry.cite_key = f"{original_key}_{counter}"
            counter += 1

        seen_keys.add(entry.cite_key)
        entries.append(entry.to_bibtex())

    logger.info("Exported %d papers to BibTeX format", len(entries))
    return "\n\n".join(entries)
