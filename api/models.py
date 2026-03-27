"""API request/response models."""
# Re-export from shared for convenience
from shared.models import AskRequest, AskResponse, LegalReference, SearchRequest, SearchResponse

__all__ = ["AskRequest", "AskResponse", "LegalReference", "SearchRequest", "SearchResponse"]
