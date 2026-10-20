"""Research paper book simulation, forward tracking, and settlement.

Canonical module in server.services.research.
"""

from __future__ import annotations

from server.services.research.research_paper_books import (
    ResearchPaperBookService,
    paper_book_code_binding,
    verify_reserved_forward_book,
)

__all__ = [
    "ResearchPaperBookService",
    "paper_book_code_binding",
    "verify_reserved_forward_book",
]
