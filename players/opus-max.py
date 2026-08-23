"""The full-depth Opus player: claude-opus-5 at max effort (the lane's default), recording into its
own knowledge lane so the effort ablation stays cleanly attributable."""

from arcade.player import Player

player = Player(
    name="opus-max",
    model="claude-opus-5",
    effort="max",
    knowledge="claude-opus-5-max",
    jobs=4,
)

if __name__ == "__main__":
    player.main()
