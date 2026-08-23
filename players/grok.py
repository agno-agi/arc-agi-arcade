"""The Grok player: xAI's flagship, playing on its own manuals."""

from arcade.player import Player

player = Player(
    name="grok-4.6",
    model="grok-4.6",
    knowledge="grok-4.6",
)

if __name__ == "__main__":
    player.main()
