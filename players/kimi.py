"""The Kimi player: the strongest open-weight all-rounder, playing on its own eyes and manuals."""

from arcade.player import Player

player = Player(
    name="kimi-k3",
    model="accounts/fireworks/models/kimi-k3",
    knowledge="kimi-k3",
)

if __name__ == "__main__":
    player.main()
