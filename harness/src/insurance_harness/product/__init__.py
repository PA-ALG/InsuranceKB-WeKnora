"""产品主数据、文档分类与产品路由（change 003，master plan P0-1）。"""

from .version_resolver import (
    RESOLVER_POLICY_HASH,
    RESOLVER_VERSION,
    FragmentProductVersionBinding,
    ProductVersionQuarantine,
    ProductVersionResolutionRequest,
    ProductVersionResolver,
    ResolutionBasis,
    ResolvedProductVersion,
    inherit_fragment_resolution,
)

__all__ = [
    "RESOLVER_POLICY_HASH",
    "RESOLVER_VERSION",
    "FragmentProductVersionBinding",
    "ProductVersionQuarantine",
    "ProductVersionResolutionRequest",
    "ProductVersionResolver",
    "ResolutionBasis",
    "ResolvedProductVersion",
    "inherit_fragment_resolution",
]
