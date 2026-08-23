"""The glm player, seeded: same model, playing from the manuals GPT wrote winning the board."""

from arcade.player import Player

player = Player(
    name="glm-5.2",
    model="accounts/fireworks/models/glm-5p2",
    knowledge="glm-5.2-seeded",
    seeds=["gpt-5.6"],
    vision=False,
)

if __name__ == "__main__":
    player.main()
