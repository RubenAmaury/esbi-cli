"""The edit plan: the only thing the LLM produces. The worker validates and applies it."""

from typing import Annotated

from annotated_types import MaxLen
from pydantic import BaseModel, BeforeValidator, Field, field_validator


def _clamp(max_items: int):
    def clamp(value):
        return value[:max_items] if isinstance(value, list) else value

    return BeforeValidator(clamp)


class ConceptEdit(BaseModel):
    """A concept or entity this source touches."""

    title: str = Field(
        min_length=2, max_length=60, description="Canonical name, short (at most 6 words)"
    )
    aliases: list[str] = Field(default_factory=list, description="Other names or acronyms")
    description: str = Field(
        min_length=10,
        description="1-3 sentences on what this source adds to this concept or entity",
    )


class Term(BaseModel):
    """A technical term used in the source, with what it means."""

    term: str = Field(
        min_length=2, max_length=60, description="Exactly as it appears in the source"
    )
    definition: str = Field(min_length=10, description="Definition in one sentence")


class Relation(BaseModel):
    """A link between two ideas, drawn later as an edge of the concept map."""

    a: str = Field(min_length=2, max_length=50)
    relation: str = Field(
        min_length=2, max_length=40, description="A short label for how the two relate"
    )
    b: str = Field(min_length=2, max_length=50)


class ChunkNotes(BaseModel):
    """What one reads out of one chunk of a long source."""

    points: Annotated[list[str], _clamp(8), MaxLen(8)] = Field(
        min_length=1,
        description="3-8 concrete statements: facts, methods, results, arguments",
    )
    terms: Annotated[list[Term], _clamp(6), MaxLen(6)] = Field(default_factory=list)
    quotes: Annotated[list[str], _clamp(3), MaxLen(3)] = Field(
        default_factory=list, description="Sentences copied EXACTLY from the chunk"
    )
    relations: Annotated[list[Relation], _clamp(6), MaxLen(6)] = Field(default_factory=list)


class Insight(BaseModel):
    idea: str = Field(min_length=10, description="The idea, in one or two sentences")
    why: str = Field(min_length=10, description="Why it matters or what it implies")


class Digest(BaseModel):
    """The long-form part of a note, written from the chunk notes."""

    abstract: str = Field(
        min_length=200,
        description="Detailed summary, 3-5 paragraphs: problem, approach, findings, implications",
    )
    insights: Annotated[list[Insight], _clamp(8), MaxLen(8)] = Field(min_length=1)
    open_questions: Annotated[list[str], _clamp(5), MaxLen(5)] = Field(default_factory=list)


class Connection(BaseModel):
    """How a new source relates to a page already in the wiki."""

    page: str = Field(description="EXACT title of an existing page")
    relation: str = Field(
        min_length=2, max_length=40, description="A short label for how the two relate"
    )
    why: str = Field(min_length=10, description="One sentence: why they are related")


class ConnectionPlan(BaseModel):
    connections: Annotated[list[Connection], _clamp(8), MaxLen(8)] = Field(default_factory=list)


class Contradiction(BaseModel):
    page: str = Field(description="EXACT title of the existing page that is contradicted")
    note: str = Field(min_length=5, description="What is contradicted, in one sentence")


class EditPlan(BaseModel):
    title: str = Field(min_length=3, description="Title of the source")
    one_liner: str = Field(min_length=10, description="One-sentence summary for the index")
    summary: str = Field(
        min_length=30, description="Executive summary: 2-3 sentences, what it is and why it matters"
    )
    abstract: str = Field(
        default="",
        description="Detailed summary, 3-5 paragraphs: problem, approach, findings, implications",
    )
    insights: Annotated[list[Insight], _clamp(8), MaxLen(8)] = Field(default_factory=list)
    terms: Annotated[list[Term], _clamp(10), MaxLen(10)] = Field(default_factory=list)
    quotes: Annotated[list[str], _clamp(6), MaxLen(6)] = Field(
        default_factory=list, description="Sentences copied EXACTLY from the source"
    )
    relations: Annotated[list[Relation], _clamp(10), MaxLen(10)] = Field(default_factory=list)
    open_questions: Annotated[list[str], _clamp(5), MaxLen(5)] = Field(default_factory=list)
    key_points: Annotated[list[str], _clamp(8), MaxLen(8)] = Field(description="3-8 key points")
    tags: Annotated[list[str], _clamp(6), MaxLen(6)] = Field(default_factory=list)
    concepts: Annotated[list[ConceptEdit], _clamp(6), MaxLen(6)] = Field(
        min_length=1, description="2-6 central concepts or techniques (never empty)"
    )
    entities: Annotated[list[ConceptEdit], _clamp(5), MaxLen(5)] = Field(default_factory=list)
    related_pages: Annotated[list[str], _clamp(6), MaxLen(6)] = Field(
        default_factory=list,
        description="EXACT titles of related existing pages (only from the given list)",
    )
    contradictions: Annotated[list[Contradiction], _clamp(4), MaxLen(4)] = Field(
        default_factory=list
    )

    @field_validator("one_liner")
    @classmethod
    def _one_liner_is_a_sentence(cls, value: str) -> str:
        if value.strip().lower().startswith(("http://", "https://")) or " " not in value.strip():
            raise ValueError("must be a descriptive sentence, not a URL")
        return value
