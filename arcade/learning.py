"""
Learning Store
==============
The agent's durable memory for one game: a custom agno LearningStore backed by agent-fs. No vector
database — a game's learnings fit in context whole, so recall is the entire file, injected at every
session start.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agno.fs import FileSystem
from agno.fs.local import LocalFileSystem
from agno.learn.stores.protocol import LearningStore

LEARNINGS_FILE = "learnings.md"


@dataclass
class GameLearningStore(LearningStore):
    """Implements agno's LearningStore protocol over a plain file in the game's run dir.

    The file lives next to trace.jsonl, so a run records exactly what the agent knew and when.
    Isolation is by construction: the store is rooted in one game's run dir, so nothing leaks
    across games.
    """

    run_dir: Path
    game_id: str
    # Distills each session's transcript into new manual entries at session end — the moment of
    # maximal knowledge, right before the context is wiped. The agent's own save_learning calls
    # remain the primary channel; the extractor catches what it didn't think to save.
    extractor: Callable[[str, str], str] | None = None
    # Every entry also lands in this per-model knowledge file (deduped), and warm=True seeds a fresh
    # run's manual from it — knowledge survives even when the trajectory starts over. seeds may point
    # at ANOTHER model's knowledge: what one model writes, any other can play from.
    knowledge: Path | None = None
    warm: bool = False
    # Extra warm-start sources, merged after the model's own knowledge (exact-line dedupe).
    seeds: list[Path] = field(default_factory=list)
    _updated: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        # Agent-fs backend: durable, quota-capped, append supports exact-line dedupe.
        self.fs = FileSystem(LocalFileSystem(root=str(self.run_dir)), namespace=self.game_id.split("-")[0])
        sources = ([self.knowledge] if self.knowledge is not None else []) + self.seeds
        if self.warm and not self.recall():
            for source in sources:
                if not source.exists():
                    continue
                for line in source.read_text().splitlines():
                    if line.strip().startswith("- "):
                        self.fs.append(LEARNINGS_FILE, f"{line.strip()}\n", unique=True)

    def _keep(self, line: str) -> None:
        """One entry, two homes: the run's manual (evidence of what this run knew) and the game's knowledge."""
        self.fs.append(LEARNINGS_FILE, f"{line}\n", unique=True)
        if self.knowledge is not None:
            self.knowledge.parent.mkdir(parents=True, exist_ok=True)
            existing = self.knowledge.read_text().splitlines() if self.knowledge.exists() else []
            if line not in {entry.strip() for entry in existing}:
                with self.knowledge.open("a") as file:
                    file.write(f"{line}\n")
        self._updated = True

    # ------------------------------------------------------------------
    # LearningStore protocol
    # ------------------------------------------------------------------
    @property
    def learning_type(self) -> str:
        return "game_knowledge"

    @property
    def schema(self) -> Any:
        return str

    def recall(self, **kwargs: Any) -> str | None:
        content = self.fs.read(LEARNINGS_FILE)
        return content.strip() if content and content.strip() else None

    async def arecall(self, **kwargs: Any) -> str | None:
        return self.recall(**kwargs)

    def process(self, messages: list[Any], **kwargs: Any) -> None:
        """Episode-end distillation: runs the extractor over the episode transcript and appends any new
        one-line learnings (exact-line dedupe). Runs in the agent's background learning future; never raises."""
        if self.extractor is None or not messages:
            return
        try:
            lines = []
            for message in messages:
                role = getattr(message, "role", "")
                content = getattr(message, "content", "")
                if isinstance(content, str) and content.strip() and role in ("user", "assistant", "tool"):
                    lines.append(f"{role}: {content.strip()}")
            transcript = "\n".join(lines)[-120_000:]
            if not transcript:
                return
            manual = self.recall() or ""
            existing = {entry.strip().removesuffix(" [auto]") for entry in manual.splitlines()}
            for line in self.extractor(transcript, manual).splitlines():
                line = line.strip()
                if line.startswith("- ") and len(line) > 12 and line not in existing:
                    self._keep(f"{line} [auto]")
        except Exception:  # noqa: BLE001 — a distillation failure must never damage the run
            return

    async def aprocess(self, messages: list[Any], **kwargs: Any) -> None:
        self.process(messages, **kwargs)

    def build_context(self, data: Any) -> str:
        body = data if data else "None saved yet — save the first mechanic you verify."
        return f"<game_learnings>\n{body}\n</game_learnings>"

    def instructions(self) -> str:
        return (
            "Your saved game learnings appear in <game_learnings>. Trust them before re-deriving "
            "anything, and call save_learning the moment you verify a new durable fact about this game."
        )

    def get_tools(self, **kwargs: Any) -> list[Callable[..., Any]]:
        def save_learning(title: str, learning: str) -> str:
            """Record one durable, VERIFIED fact about this game for your future sessions: an action's
            semantic, a hazard, how a level's goal is recognized, a mechanic. One line; be exact."""
            self._keep(f"- {title}: {learning}")
            return f"saved: {title}"

        return [save_learning]

    async def aget_tools(self, **kwargs: Any) -> list[Callable[..., Any]]:
        return self.get_tools(**kwargs)

    @property
    def was_updated(self) -> bool:
        return self._updated
