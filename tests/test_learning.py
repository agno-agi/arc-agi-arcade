"""GameLearningStore — agentic saving, auto-distillation, cross-run knowledge. No engine, no model."""

from types import SimpleNamespace

from arcade.learning import GameLearningStore

GAME = "lf52-271a04aa"


def manual_of(store: GameLearningStore) -> str:
    text = store.recall()
    assert text is not None
    return text


def messages(*texts):
    return [SimpleNamespace(role="assistant", content=text) for text in texts]


def test_agentic_save_recall_dedupe(tmp_path):
    store = GameLearningStore(run_dir=tmp_path, game_id=GAME)
    save = store.get_tools()[0]
    assert store.recall() is None
    save("Jump", "click peg then hole two cells away")
    save("Jump", "click peg then hole two cells away")  # exact duplicate
    assert manual_of(store).count("Jump") == 1
    assert "<game_learnings>" in store.build_context(store.recall())


def test_auto_distillation_tags_dedupes_and_is_idempotent(tmp_path):
    store = GameLearningStore(
        run_dir=tmp_path,
        game_id=GAME,
        extractor=lambda transcript, manual: "- New: fact one (verified)\n- Old: known\nnoise\n- X: y",
    )
    store.get_tools()[0]("Old", "known")
    store.process(messages("tried ACTION5"))
    store.process(messages("tried ACTION5"))
    manual = manual_of(store)
    assert manual.count("known") == 1  # cross-tag dedupe against the agentic entry
    assert "fact one (verified) [auto]" in manual
    assert "noise" not in manual and "- X: y" not in manual  # non-bullets and too-short lines dropped


def test_extractor_sees_transcript_without_system_messages(tmp_path):
    seen = {}

    def extractor(transcript, manual):
        seen["transcript"] = transcript
        return ""

    store = GameLearningStore(run_dir=tmp_path, game_id=GAME, extractor=extractor)
    store.process(
        [
            SimpleNamespace(role="system", content="EXCLUDED"),
            SimpleNamespace(role="tool", content="state=NOT_FINISHED"),
            SimpleNamespace(role="assistant", content="probing"),
        ]
    )
    assert "EXCLUDED" not in seen["transcript"] and "probing" in seen["transcript"]


def test_extractor_crash_is_swallowed(tmp_path):
    def broken(transcript: str, manual: str) -> str:
        raise ZeroDivisionError

    store = GameLearningStore(run_dir=tmp_path, game_id=GAME, extractor=broken)
    store.process(messages("anything"))  # must not raise


def test_knowledge_promotion_cold_isolation_warm_seed(tmp_path):
    knowledge = tmp_path / "knowledge" / f"{GAME}.md"
    first = GameLearningStore(run_dir=tmp_path / "run1", game_id=GAME, knowledge=knowledge)
    first.get_tools()[0]("Jump", "two cells")
    assert knowledge.exists() and knowledge.read_text().count("- ") == 1

    cold = GameLearningStore(run_dir=tmp_path / "run2", game_id=GAME, knowledge=knowledge, warm=False)
    assert cold.recall() is None

    warm = GameLearningStore(run_dir=tmp_path / "run3", game_id=GAME, knowledge=knowledge, warm=True)
    assert "Jump" in manual_of(warm)
    warm.get_tools()[0]("Extra", "still contributes")
    assert knowledge.read_text().count("- ") == 2


def test_cross_model_seed(tmp_path):
    opus_lib = tmp_path / "knowledge" / "claude-opus-5" / f"{GAME}.md"
    teacher = GameLearningStore(run_dir=tmp_path / "opus-run", game_id=GAME, knowledge=opus_lib)
    teacher.get_tools()[0]("Peg jump", "click peg then hole two cells away")

    # A different model warm-starts from the teacher's knowledge, writes to its own knowledge.
    glm_lib = tmp_path / "knowledge" / "glm-5.3" / f"{GAME}.md"
    student = GameLearningStore(
        run_dir=tmp_path / "glm-run", game_id=GAME, knowledge=glm_lib, warm=True, seeds=[opus_lib]
    )
    assert "Peg jump" in manual_of(student)

    # A student with its OWN banked knowledge keeps it AND gains the seed (merged, own first).
    glm_lib.parent.mkdir(parents=True, exist_ok=True)
    glm_lib.write_text("- Own fact: banked earlier\n")
    merged = GameLearningStore(
        run_dir=tmp_path / "glm-run2", game_id=GAME, knowledge=glm_lib, warm=True, seeds=[opus_lib]
    )
    assert "Own fact" in manual_of(merged) and "Peg jump" in manual_of(merged)
    student.get_tools()[0]("New", "learned by the student")
    assert "learned by the student" in glm_lib.read_text()
    assert "learned by the student" not in opus_lib.read_text()  # teacher's knowledge untouched
