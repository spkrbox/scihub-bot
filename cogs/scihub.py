import logging
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from utils.scraper import SciHubScraper

logger = logging.getLogger("sci.hub.cog")


class DownloadButton(discord.ui.Button):
    def __init__(self, url: str):
        super().__init__(
            label="Download PDF", style=discord.ButtonStyle.link, url=url, emoji="📥"
        )


class SciHub(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.scraper = SciHubScraper()
        logger.info("SciHub cog initialized")

    async def cog_load(self):
        """Initialize scraper when cog is loaded."""
        await self.scraper.init()
        logger.info("SciHub scraper initialized")

    async def cog_unload(self):
        """Close scraper when cog is unloaded."""
        await self.scraper.close()
        logger.info("SciHub scraper closed")

    @app_commands.command(
        name="paper",
        description="Retrieve a paper from Sci-Hub using DOI or URL containing DOI",
    )
    async def paper(self, interaction: discord.Interaction, query: str):
        await interaction.response.defer()
        logger.info(
            f"Paper request received from {interaction.user} (ID: {interaction.user.id})"
        )
        logger.debug(f"Query: {query}")

        doi = self.scraper.extract_doi(query) or query
        logger.info(f"Extracted/Using DOI: {doi}")

        initial_message = await interaction.followup.send(
            f"<a:loadinghearts:1338247797702529074> Searching for paper with DOI: `{doi}`..."
        )

        try:
            pdf_url, domain, metadata, preview = await self.scraper.get_paper(doi)

            if pdf_url:
                logger.info(f"Successfully retrieved paper from {domain}")
                embed = self._create_paper_embed(doi, domain, metadata)
                view = discord.ui.View()
                view.add_item(DownloadButton(pdf_url))

                if preview:
                    file = discord.File(preview, filename="preview.png")
                    embed.set_thumbnail(url="attachment://preview.png")
                    await initial_message.edit(
                        content=None, embed=embed, view=view, attachments=[file]
                    )
                else:
                    await initial_message.edit(
                        content=None, embed=embed, view=view, attachments=[]
                    )
            else:
                logger.warning(f"Failed to retrieve paper for DOI: {doi}")
                error_embed = discord.Embed(
                    title="Error 🚫",
                    description="Failed to retrieve the paper from all available mirrors.",
                    color=discord.Color.red(),
                )
                await initial_message.edit(
                    content=None, embed=error_embed, attachments=[]
                )
        except Exception as e:
            logger.error(f"Error processing paper request: {str(e)}", exc_info=True)
            await initial_message.edit(
                content="An unexpected error occurred while processing your request.",
                attachments=[],
            )

    def _create_paper_embed(
        self, doi: str, domain: str, metadata: Optional[dict]
    ) -> discord.Embed:
        """Create embed for paper response."""
        embed = discord.Embed(
            title=metadata.get("title", "Paper Found! 📚"),
            color=discord.Color.green(),
            url=f"https://doi.org/{doi}",
        )

        if metadata:
            for field, value in metadata.items():
                if field == "title":
                    continue
                is_inline = field != "author"
                embed.add_field(name=field.title(), value=value, inline=is_inline)

        embed.add_field(name="DOI", value=doi, inline=False)
        return embed


async def setup(bot: commands.Bot):
    await bot.add_cog(SciHub(bot))
