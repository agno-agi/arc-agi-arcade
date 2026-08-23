"""The grok player, seeded: same model, playing from the manuals GPT wrote winning the board."""

from arcade.player import Player

player = Player(
    name="grok-4.6",
    model="grok-4.6",
    knowledge="grok-4.6-seeded",
    seeds=["gpt-5.6"],
)

if __name__ == "__main__":
    player.main()
