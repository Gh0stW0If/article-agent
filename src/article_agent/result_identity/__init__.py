"""Source-preserving canonical identity projections; no API, Gold, or result-value matching."""
from .projection import canonicalize_source_outcomes, project_results
from .matcher import link_outcomes, link_results
from .models import ResultIdentityProjection, SourceIdentityContext

__all__ = ["canonicalize_source_outcomes", "project_results", "link_outcomes", "link_results",
           "ResultIdentityProjection", "SourceIdentityContext"]
