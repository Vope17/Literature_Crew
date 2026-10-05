"""Shared search filters translated to each provider's query format."""

from datetime import date

from pydantic import BaseModel, Field, field_validator, model_validator

AREAS = {
    "all": ("All subjects", (), None),
    "computer_science": ("Computer science", ("cs.*",), "Computer Science"),
    "mathematics": ("Mathematics", ("math.*",), "Mathematics"),
    "physics": ("Physics", (
        "physics.*", "astro-ph.*", "cond-mat.*", "gr-qc", "hep-ex", "hep-lat",
        "hep-ph", "hep-th", "math-ph", "nlin.*", "nucl-ex", "nucl-th", "quant-ph",
    ), "Physics"),
    "biology": ("Biology", ("q-bio.*",), "Biology"),
    "economics": ("Economics", ("econ.*",), "Economics"),
    "engineering": ("Electrical engineering", ("eess.*",), "Engineering"),
}


class SearchFilters(BaseModel):
    area: str = "all"
    year_from: int | None = Field(default=None, ge=1900)
    year_to: int | None = Field(default=None, ge=1900)

    @field_validator("area")
    @classmethod
    def known_area(cls, value):
        if value not in AREAS:
            raise ValueError("Unknown subject area.")
        return value

    @model_validator(mode="after")
    def valid_years(self):
        if any(year and year > date.today().year + 1 for year in (self.year_from, self.year_to)):
            raise ValueError("Year is too far in the future.")
        if self.year_from and self.year_to and self.year_from > self.year_to:
            raise ValueError("Start year must not be later than end year.")
        return self

    def arxiv_query(self, query: str) -> str:
        clauses = []
        categories = AREAS[self.area][1]
        if categories:
            clauses.append("(" + " OR ".join(f"cat:{category}" for category in categories) + ")")
        if self.year_from or self.year_to:
            start = self.year_from or 1900
            end = self.year_to or date.today().year + 1
            clauses.append(f"submittedDate:[{start}01010000 TO {end}12312359]")
        return " AND ".join([f"({query})", *clauses]) if clauses else query

    def semantic_params(self) -> dict[str, str]:
        params = {}
        field = AREAS[self.area][2]
        if field:
            params["fieldsOfStudy"] = field
        if self.year_from or self.year_to:
            params["year"] = f"{self.year_from or ''}-{self.year_to or ''}"
        return params

    def includes_year(self, year: int) -> bool:
        return (self.year_from is None or year >= self.year_from) and (self.year_to is None or year <= self.year_to)

    def cache_key(self):
        return self.area, self.year_from, self.year_to
