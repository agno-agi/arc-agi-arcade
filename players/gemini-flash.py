"""The Gemini Flash player: Google's fast tier, playing on its own manuals."""

from arcade.player import Player

player = Player(
    name="gemini-3.7-flash",
    model="gemini-3.7-flash",
    knowledge="gemini-3.7-flash",
)

if __name__ == "__main__":
    player.main()
