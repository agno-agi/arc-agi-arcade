"""
ARC Agent
=========
Creates the Agno agent that plays an unfamiliar ARC game through interaction. This is the default
composition; a player may bring its own with `agent="module:factory"` or `agent="path/to/file.py:factory"`
— the factory is called with the same arguments as create_agent and returns the Agent that plays.
"""

from collections.abc import Callable
from importlib import import_module, util
from inspect import signature
from pathlib import Path
from typing import Any

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.learn import LearningMachine
from agno.tools.code import CodeMode

from arcade.instructions import ENDING_PART, KERNEL_PART, KERNEL_SETUP, LEARN_PART, PLAY_PART
from arcade.knowledge import knowledge_file
from arcade.learning import GameLearningStore
from arcade.models import episode_extractor, get_model
from arcade.tools import ArcadeTools

REPO = Path(__file__).parent.parent


def resolve_agent_factory(spec: str | None) -> Callable[..., Agent]:
    """The agent factory a player asked for: None means the arcade's own create_agent; otherwise
    `module.path:callable` or `path/to/file.py:callable` (callable defaults to create_agent, file paths
    resolve against the repo). Resolution fails loudly BEFORE a game is opened or a token is spent."""
    if not spec:
        return create_agent
    target, _, name = spec.partition(":")
    name = name or "create_agent"
    if target.endswith(".py"):
        path = Path(target) if Path(target).is_absolute() else REPO / target
        if not path.exists():
            raise RuntimeError(f"agent file not found: {path}")
        module_spec = util.spec_from_file_location(f"arcade_player_agent_{path.stem}", path)
        if module_spec is None or module_spec.loader is None:
            raise RuntimeError(f"could not load agent file: {path}")
        module = util.module_from_spec(module_spec)
        try:
            module_spec.loader.exec_module(module)
        except Exception as error:  # noqa: BLE001 — surface the user's import failure as itself, not as a
            raise RuntimeError(f"agent file {path} failed to import: {error!r}")  # misdiagnosed engine error
    else:
        try:
            module = import_module(target)
        except Exception as error:  # noqa: BLE001
            raise RuntimeError(f"agent module {target!r} failed to import: {error!r}")
    factory = getattr(module, name, None)
    if not callable(factory):
        raise RuntimeError(f"agent factory {name!r} not found in {target}")
    try:  # the runner calls factory(game, model, knowledge=, warm=, seeds=, effort=) — refuse a factory
        signature(factory).bind(None, "model", knowledge=None, warm=False, seeds=[], effort=None)
    except TypeError as error:
        raise RuntimeError(f"agent factory {name!r} does not accept the create_agent signature: {error}")
    return factory


def create_agent(
    game: ArcadeTools,
    model: str = "gpt-5.6",
    knowledge: str | None = None,
    warm: bool = False,
    seeds: list[str] | None = None,
    effort: str | None = None,
) -> Agent:
    """
    Create an Agno agent that plays an unfamiliar ARC game through interaction.

    - knowledge: the agent's knowledge dir under knowledge/ (default: the model id)
    - warm: seed the game manual from that knowledge before play
    - seeds: warm-start from these OTHER models' knowledge instead
    - effort: reasoning-depth override for the model lane (see arcade.models.get_model)
    """

    # Database for the agent's sessions and learning bookkeeping (knowledge itself lives in files)
    db_dir = game.run_dir or Path(__file__).parent.parent / "tmp"
    db_dir.mkdir(parents=True, exist_ok=True)
    db = SqliteDb(db_file=str(db_dir / "agent.db"))

    # Tools for the agent
    # - game: the ARC environment toolkit
    # - CodeMode: the stateful Python kernel for free analysis
    tools: list[Any] = [game, CodeMode(allow_shell=False, timeout=120, startup_code=KERNEL_SETUP)]

    # Learning store for the agent (passing seeds implies warm; a provider path like
    # "accounts/fireworks/models/glm-5p2" defaults its knowledge dir to the last segment)
    game_id = game.env.info.game_id
    store = GameLearningStore(
        run_dir=db_dir,
        game_id=game_id,
        extractor=episode_extractor(game, model),
        knowledge=knowledge_file(knowledge or model.split("/")[-1], game_id),
        warm=warm or bool(seeds),
        seeds=[knowledge_file(source, game_id) for source in seeds or []],
    )

    # Create the agent
    play_part = PLAY_PART if game.images else PLAY_PART.replace(" (the image is a lossy aid)", "")
    return Agent(
        model=get_model(model, game.meter, effort),
        db=db,
        tools=tools,
        learning=LearningMachine(db=db, custom_stores={"game": store}),
        offload_tool_results=True,  # long kernel outputs get offloaded and become pointers
        # Text-only models must not be told about an image they never receive.
        instructions="\n\n".join((play_part, KERNEL_PART, LEARN_PART, ENDING_PART)),
    )
