"""The deepseek player, seeded: same model, playing from the manuals GPT wrote winning the board."""

from arcade.player import Player

player = Player(
    name="deepseek-v4-flash",
    model="deepseek-v4-flash",
    knowledge="deepseek-v4-flash-seeded",
    seeds=["gpt-5.6"],
    vision=False,
)

if __name__ == "__main__":
    player.main()
