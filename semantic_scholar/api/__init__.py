"""
API endpoints for the Semantic Scholar API Server.
"""

# Import all endpoints to make them available when importing the package
from .papers import (
    paper_relevance_search,
    paper_bulk_search,
    paper_title_search,
    paper_details,
    paper_batch_details,
    paper_authors,
    paper_citations,
    paper_references
)

from .authors import (
    author_search,
    author_details,
    author_papers,
    author_batch_details
)

from .recommendations import (
    get_paper_recommendations_single,
    get_paper_recommendations_multi
) 