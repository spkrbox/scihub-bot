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
            label="Download",
            style=discord.ButtonStyle.link,
            url=url,
            emoji="<:pdf:1338514643131564134>",
        )


class CitationButton(discord.ui.Button):
    def __init__(self, citation: str):
        super().__init__(
            label="Citation",
            style=discord.ButtonStyle.secondary,
            emoji="<:quote:1338527790324256799>",
            custom_id="citation",
        )
        self.citation = citation

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            f"```{self.citation}```", ephemeral=True
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

    async def _update_message(
        self, message, content=None, embed=None, view=None, file=None
    ):
        """Helper method to update messages."""
        kwargs = {
            "content": content,
            "embed": embed,
            "view": view,
            "attachments": [file] if file else [],
        }
        await message.edit(**kwargs)

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
            (
                pdf_url,
                domain,
                metadata,
                preview,
                citation,
            ) = await self.scraper.get_paper(doi)

            if pdf_url:
                logger.info(f"Successfully retrieved paper from {domain}")
                embed = self._create_paper_embed(doi, domain, metadata)
                view = discord.ui.View()
                view.add_item(DownloadButton(pdf_url))
                if citation:
                    view.add_item(CitationButton(citation))

                if preview:
                    file = discord.File(preview, filename="preview.png")
                    embed.set_thumbnail(url="attachment://preview.png")
                    await self._update_message(
                        initial_message, embed=embed, view=view, file=file
                    )
                else:
                    await self._update_message(
                        initial_message, embed=embed, view=view, file=None
                    )
            else:
                logger.warning(f"Failed to retrieve paper for DOI: {doi}")
                error_embed = discord.Embed(
                    title="Error 🚫",
                    description="Failed to retrieve the paper from all available mirrors.",
                    color=discord.Color.red(),
                )
                await self._update_message(
                    initial_message, embed=error_embed, file=None
                )
        except Exception as e:
            logger.error(f"Error processing paper request: {str(e)}", exc_info=True)
            await self._update_message(
                initial_message,
                content="An unexpected error occurred while processing your request.",
                file=None,
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
