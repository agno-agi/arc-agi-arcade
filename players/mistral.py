"""The Mistral player: Europe's lane, playing on its own manuals."""

from arcade.player import Player

player = Player(
    name="mistral-large",
    model="mistral-large-latest",
    knowledge="mistral-large",
)

if __name__ == "__main__":
    player.main()
