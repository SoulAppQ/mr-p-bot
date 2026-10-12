"""
Roles Management Cog.
Handles self-serve game roles and cosmetic color roles.
"""
import discord
from discord import app_commands
from discord.ext import commands
from typing import Optional

from config.settings import settings, get_all_games
from utils.helpers import ava_embed


class GameRoleSelect(discord.ui.Select):
    """Dropdown for selecting game roles."""

    def __init__(self, guild: discord.Guild):
        self.guild = guild
        games = get_all_games()
        options = [
            discord.SelectOption(
                label=game_info["name"],
                value=game_key,
                emoji="🎮"
            )
            for game_key, game_info in list(games.items())[:25]  # Max 25 options
        ]
        super().__init__(
            placeholder="Select a game role...",
            options=options,
            min_values=0,
            max_values=5  # Can select up to 5 games
        )

    async def callback(self, interaction: discord.Interaction):
        """Handle game role selection."""
        await interaction.response.defer(ephemeral=True)

        selected_values = self.values
        games = get_all_games()

        added_roles = []
        removed_roles = []

        # Get all game roles in the server
        for game_key, game_info in games.items():
            game_name = game_info["name"]
            role = None
            for r in self.guild.roles:
                if r.name.lower() == game_name.lower():
                    role = r
                    break

            if not role:
                continue

            # Add or remove role based on selection
            if game_key in selected_values:
                if role not in interaction.user.roles:
                    try:
                        await interaction.user.add_roles(role)
                        added_roles.append(game_name)
                    except discord.HTTPException:
                        pass
            else:
                if role in interaction.user.roles:
                    try:
                        await interaction.user.remove_roles(role)
                        removed_roles.append(game_name)
                    except discord.HTTPException:
                        pass

        desc = ""
        if added_roles:
            desc += f"✅ Added: {', '.join(added_roles)}\n"
        if removed_roles:
            desc += f"❌ Removed: {', '.join(removed_roles)}\n"
        if not desc:
            desc = "⚠️ No changes made."

        embed = ava_embed(title="🎭 Game Roles", description=desc, footer_cmd="roles")
        await interaction.followup.send(embed=embed, ephemeral=True)


class GameRoleSelectView(discord.ui.View):
    """View for game role selection."""

    def __init__(self, guild: discord.Guild):
        super().__init__()
        self.add_item(GameRoleSelect(guild))


class ColorRoleSelect(discord.ui.Select):
    """Dropdown for selecting cosmetic color roles."""

    COLORS = {
        "red": 0xFF0000,
        "orange": 0xFFA500,
        "yellow": 0xFFFF00,
        "green": 0x00FF00,
        "blue": 0x0000FF,
        "purple": 0x800080,
        "pink": 0xFFC0CB,
        "cyan": 0x00FFFF,
    }

    def __init__(self, guild: discord.Guild):
        self.guild = guild
        options = [
            discord.SelectOption(label=color.capitalize(), value=color, emoji="⭕")
            for color in self.COLORS.keys()
        ]
        super().__init__(
            placeholder="Select your color...",
            options=options,
            min_values=1,
            max_values=1
        )

    async def callback(self, interaction: discord.Interaction):
        """Handle color role selection."""
        await interaction.response.defer(ephemeral=True)

        selected_color = self.values[0]

        # Find or create role
        role_name = f"Color: {selected_color.capitalize()}"
        role = None
        for r in self.guild.roles:
            if r.name == role_name:
                role = r
                break

        if not role:
            try:
                role = await self.guild.create_role(
                    name=role_name,
                    color=discord.Color(self.COLORS[selected_color])
                )
            except discord.HTTPException:
                embed = ava_embed(title="⭕ Color Roles", description="Could not create color role.",
                                  footer_cmd="roles")
                await interaction.followup.send(embed=embed, ephemeral=True)
                return

        # Remove user from other color roles
        for other_role in self.guild.roles:
            if other_role.name.startswith("Color:") and other_role != role:
                if other_role in interaction.user.roles:
                    try:
                        await interaction.user.remove_roles(other_role)
                    except discord.HTTPException:
                        pass

        # Add user to selected color role
        if role not in interaction.user.roles:
            try:
                await interaction.user.add_roles(role)
            except discord.HTTPException:
                embed = ava_embed(title="⭕ Color Roles", description="Could not apply color role.",
                                  footer_cmd="roles")
                await interaction.followup.send(embed=embed, ephemeral=True)
                return

        embed = ava_embed(title="⭕ Color Roles",
                          description=f"Your color is now **{selected_color.capitalize()}**! 🎉",
                          footer_cmd="roles")
        await interaction.followup.send(embed=embed, ephemeral=True)


class ColorRoleSelectView(discord.ui.View):
    """View for color role selection."""

    def __init__(self, guild: discord.Guild):
        super().__init__()
        self.add_item(ColorRoleSelect(guild))


class RolesCog(commands.Cog):
    """Roles management and self-serve role assignment."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="roles", description="View and manage your game and color roles")
    async def roles(self, interaction: discord.Interaction):
        """Display role management interface."""
        await interaction.response.defer()

        embed = ava_embed(
            title="🎮 Role Management",
            description="Select your game roles and customize your color!",
            footer_cmd="roles",
            fields=[
                ("Game Roles", "Choose which games you play", False),
                ("Color Roles", "Pick your favorite color for your display name", False),
            ]
        )

        # Create view with tabs
        view = discord.ui.View()

        game_button = discord.ui.Button(label="Game Roles", style=discord.ButtonStyle.blurple, emoji="🎮")
        color_button = discord.ui.Button(label="Color Roles", style=discord.ButtonStyle.blurple, emoji="⭕")

        async def game_button_callback(inter: discord.Interaction):
            await inter.response.defer(ephemeral=True)
            select_embed = ava_embed(
                title="🎮 Game Roles",
                description="Choose which games you play:",
                footer_cmd="roles",
            )
            await inter.followup.send(embed=select_embed, view=GameRoleSelectView(inter.guild), ephemeral=True)

        async def color_button_callback(inter: discord.Interaction):
            await inter.response.defer(ephemeral=True)
            select_embed = ava_embed(
                title="⭕ Color Roles",
                description="Pick your display color:",
                footer_cmd="roles",
            )
            await inter.followup.send(embed=select_embed, view=ColorRoleSelectView(inter.guild), ephemeral=True)

        game_button.callback = game_button_callback
        color_button.callback = color_button_callback

        view.add_item(game_button)
        view.add_item(color_button)

        await interaction.followup.send(embed=embed, view=view)

    @app_commands.command(name="setup-role-directory", description="Setup the role management directory (admin only)")
    @app_commands.default_permissions(administrator=True)
    async def setup_role_directory(self, interaction: discord.Interaction):
        """Setup the role directory in a designated channel."""
        await interaction.response.defer(ephemeral=True)

        if settings.channel_roles_directory == 0:
            embed = ava_embed(title="🎭 Role Setup",
                              description="No roles directory channel configured in settings.",
                              footer_cmd="setup-role-directory")
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        channel = interaction.guild.get_channel(settings.channel_roles_directory)
        if not channel:
            embed = ava_embed(title="🎭 Role Setup",
                              description="Roles directory channel not found.",
                              footer_cmd="setup-role-directory")
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        embed = ava_embed(
            title="🎭 Role Selection Hub",
            description="Use the buttons below to manage your roles!",
            footer_cmd="roles",
        )

        view = discord.ui.View()

        game_button = discord.ui.Button(label="Game Roles", style=discord.ButtonStyle.blurple, emoji="🎮")
        color_button = discord.ui.Button(label="Color Roles", style=discord.ButtonStyle.blurple, emoji="⭕")

        async def game_button_callback(inter: discord.Interaction):
            select_embed = ava_embed(
                title="🎮 Game Roles",
                description="Choose which games you play:",
                footer_cmd="roles",
            )
            await inter.response.send_message(embed=select_embed, view=GameRoleSelectView(inter.guild), ephemeral=True)

        async def color_button_callback(inter: discord.Interaction):
            select_embed = ava_embed(
                title="⭕ Color Roles",
                description="Pick your display color:",
                footer_cmd="roles",
            )
            await inter.response.send_message(embed=select_embed, view=ColorRoleSelectView(inter.guild), ephemeral=True)

        game_button.callback = game_button_callback
        color_button.callback = color_button_callback

        view.add_item(game_button)
        view.add_item(color_button)

        await channel.send(embed=embed, view=view)
        embed = ava_embed(title="🎭 Role Setup",
                          description="Role directory setup complete! ✅",
                          footer_cmd="setup-role-directory")
        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    """Setup the cog."""
    await bot.add_cog(RolesCog(bot))