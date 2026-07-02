"""Internal Pydantic models for session tracking, BibTeX export, and author
consolidation.

These models are used only by paper_tracker.py, bibtex.py, tracking_hook.py,
and the consolidate_authors/find_duplicate_authors tools. Every other tool in
this server returns raw API response dicts; parsing a dict into one of these
models is always best-effort (see tracking_hook.py) and never changes what a
tool call returns to its caller.
"""

from pydantic import BaseModel, field_validator


class AuthorExternalIds(BaseModel):
    ORCID: str | None = None
    DBLP: str | list[str] | None = None


class PaperExternalIds(BaseModel):
    DOI: str | None = None
    ArXiv: str | None = None
    MAG: str | None = None
    ACL: str | None = None
    PubMed: str | None = None
    PubMedCentral: str | None = None
    DBLP: str | None = None
    CorpusId: int | None = None


class Journal(BaseModel):
    name: str | None = None
    volume: str | None = None
    pages: str | None = None


class PublicationVenue(BaseModel):
    id: str | None = None
    name: str | None = None
    type: str | None = None
    alternate_names: list[str] | None = None
    issn: str | None = None
    url: str | None = None


class OpenAccessPdf(BaseModel):
    url: str | None = None
    status: str | None = None


class Author(BaseModel):
    authorId: str | None = None
    name: str | None = None
    affiliations: list[str] | None = None
    paperCount: int | None = None
    citationCount: int | None = None
    hIndex: int | None = None
    aliases: list[str] | None = None
    homepage: str | None = None
    externalIds: AuthorExternalIds | None = None


class Paper(BaseModel):
    paperId: str | None = None
    title: str | None = None
    abstract: str | None = None
    year: int | None = None
    citationCount: int | None = None
    authors: list[Author] | None = None
    venue: str | None = None
    publicationTypes: list[str] | None = None
    openAccessPdf: OpenAccessPdf | None = None
    fieldsOfStudy: list[str] | None = None
    journal: Journal | None = None
    externalIds: PaperExternalIds | None = None
    publicationDate: str | None = None
    publicationVenue: PublicationVenue | None = None

    @field_validator("publicationVenue", mode="before")
    @classmethod
    def coerce_publication_venue(cls, v: object) -> object:
        """Coerce plain venue ID strings into PublicationVenue objects.

        The Semantic Scholar recommendations endpoint sometimes returns
        ``publicationVenue`` as a bare UUID string instead of the full venue
        object. Without this, Pydantic rejects the string.
        """
        if isinstance(v, str):
            return PublicationVenue(id=v)
        return v


class AuthorGroup(BaseModel):
    primary_author: Author
    candidates: list[Author]
    match_reasons: list[str]


class AuthorConsolidationResult(BaseModel):
    merged_author: Author
    source_authors: list[Author]
    match_type: str
    confidence: float | None = None
    is_preview: bool = True
    notes: list[str] | None = None
