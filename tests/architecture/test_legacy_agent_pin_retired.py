"""Agent turns no longer pin old 830 releases (S7d-2c-3a).

The 830 concept Agent service, its turn types and the release-wrapping wiki tools are gone; an Agent
turn decides native reads with the platform's managed-KB classifier instead. Standard library only.
Run from the repository root:  python -m pytest -q tests/architecture
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import REPO_ROOT  # noqa: E402

RETIRED = (
    "internal/application/service/concept_agent_830_g2.go",
    "internal/types/interfaces/concept_agent_830_g2.go",
    "internal/agent/tools/wiki_release_830_g2.go",
)
WIRED = ("internal/application/service/agent_service.go", "internal/container/container.go")
GONE = (
    "ConceptAgentService830G2",
    "ConceptAgentTurnProvider830G2",
    "PinConceptAgentTurn830G2",
    "WikiReleaseReadPageTool830G2",
    "WikiReleaseSearchTool830G2",
)


def test_the_pinning_service_and_tools_are_gone() -> None:
    assert [rel for rel in RETIRED if (REPO_ROOT / rel).exists()] == []


def test_the_agent_and_the_container_no_longer_wire_them() -> None:
    for rel in WIRED:
        source = (REPO_ROOT / rel).read_text(encoding="utf-8")
        assert [name for name in GONE if name in source] == [], rel
