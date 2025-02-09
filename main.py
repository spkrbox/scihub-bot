import asyncio
import logging
import os
import sys
from pathlib import Path

import discord
from discord.ext import commands
from discord.ext.commands import when_mentioned_or
from dotenv import load_dotenv
from rich.logging import RichHandler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        RichHandler(rich_tracebacks=True),
        logging.FileHandler(filename="sci_hub.log", encoding="utf-8"),
    ],
)

logger = logging.getLogger("sci.hub")


class SciHubBot(commands.AutoShardedBot):
    """A Discord bot for retrieving papers from Sci-Hub."""

    def __init__(self):
        intents = discord.Intents.default()

        super().__init__(
            command_prefix=when_mentioned_or("sh!"),
            intents=intents,
            description="A bot to fetch papers from Sci-Hub",
        )
        self.logger = logger

    async def setup_hook(self) -> None:
        """Initialize the bot, load extensions."""
        await self.load_extensions()

    async def load_extensions(self) -> None:
        """Load all extensions from the cogs directory."""
        cogs_dir = Path("cogs")
        for cog_file in cogs_dir.glob("*.py"):
            if cog_file.stem != "__init__":
                try:
                    await self.load_extension(f"cogs.{cog_file.stem}")
                    self.logger.info(
                        f"Successfully loaded extension '{cogs_dir.name}.{cog_file.stem}'"
                    )
                except Exception as e:
                    self.logger.error(
                        f"Failed to load extension {cog_file.stem}: {str(e)}",
                        exc_info=True,
                    )

    async def on_ready(self):
        """Called when the bot is ready."""
        self.logger.info(f"Logged in as {self.user} (ID: {self.user.id})")
        try:
            await self.tree.sync()
            self.logger.info("Successfully synced application commands")
        except Exception:
            self.logger.error("Failed to sync application commands", exc_info=True)
        self.logger.info("Bot is ready!")


async def main():
    load_dotenv()

    TOKEN = os.environ.get("DISCORD_TOKEN")

    if not TOKEN:
        logger.error("No Discord token found in environment variables!")
        sys.exit(1)

    async with SciHubBot() as bot:
        try:
            await bot.start(TOKEN)
        except Exception as e:
            logger.error(f"Fatal error: {str(e)}", exc_info=True)
            sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
