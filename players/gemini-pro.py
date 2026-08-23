"""The Gemini Pro player: Google's flagship reasoner, playing on its own manuals."""

from arcade.player import Player

player = Player(
    name="gemini-3.1-pro",
    model="gemini-3.1-pro-preview",
    knowledge="gemini-3.1-pro",
)

if __name__ == "__main__":
    player.main()
