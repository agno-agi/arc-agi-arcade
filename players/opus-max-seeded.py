"""The Opus player, seeded: claude-opus-5 at max effort, playing from the manuals GPT wrote winning
the board — the transfer test on the board's weakest cold performer."""

from arcade.player import Player

player = Player(
    name="opus-max",
    model="claude-opus-5",
    effort="max",
    knowledge="claude-opus-5-max-seeded",
    seeds=["gpt-5.6"],
    jobs=4,
)

if __name__ == "__main__":
    player.main()
