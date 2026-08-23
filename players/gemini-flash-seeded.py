"""The Gemini Flash player, seeded: same model, playing from the manuals GPT wrote winning the board."""

from arcade.player import Player

player = Player(
    name="gemini-3.7-flash",
    model="gemini-3.7-flash",
    knowledge="gemini-3.7-flash-seeded",
    seeds=["gpt-5.6"],
)

if __name__ == "__main__":
    player.main()
