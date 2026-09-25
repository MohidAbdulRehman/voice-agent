"""Run the voice agent: ``python -m intake.agent console|dev|start``.

``console`` talks to the agent in the terminal (add ``--text`` to type instead of
speaking); ``dev`` registers it with LiveKit Cloud for the phone number and the
playground; ``start`` is the production mode LiveKit Cloud runs.
"""

from livekit.agents import cli

from intake.agent.session import build_server
from intake.config import get_settings


def main() -> None:
    """Hand the agent server to LiveKit's command line."""
    cli.run_app(build_server(get_settings()))


if __name__ == "__main__":
    main()
