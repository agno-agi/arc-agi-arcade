"""The reduced-reasoning Opus player: claude-opus-5 at high effort, recording into its own
knowledge lane so the effort ablation stays cleanly attributable."""

from arcade.player import Player

player = Player(
    name="opus-high",
    model="claude-opus-5",
    effort="high",
    knowledge="claude-opus-5-high",
    jobs=4,
)

if __name__ == "__main__":
    player.main()
