"""
Knowledge
=========
The per-model game learnings stored under knowledge/: written entirely by the agent in play.
"""

from pathlib import Path

KNOWLEDGE_ROOT = Path(__file__).parent.parent / "knowledge"


def knowledge_file(name: str, game_id: str) -> Path:
    """The manual for one game in one knowledge dir: knowledge/<name>/<game_id>.md."""
    return KNOWLEDGE_ROOT / name / f"{game_id}.md"
