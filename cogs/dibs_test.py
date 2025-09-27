import discord
from discord.ext import commands
import asyncio
import time
import asyncpg
from cogs.tools import Tools
from data.data_hunting_zone import letter_emojis, excluded_roles
from config import POSTGRES, DIBS_TIME, FARM_TIME, BLACKLIST_TIME, GLOBAL_BLACKLIST_TIME

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)
active_dibs = []

class Spots(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.bot.db = None
        self.channel = None
        self.spots = None
        self.hunting_embed_msg = None
        self.letters_emoji = letter_emojis
        self.dibs_time = DIBS_TIME
        self.farm_time = FARM_TIME
        self.blacklist_time = BLACKLIST_TIME
        self.global_blacklist_time = GLOBAL_BLACKLIST_TIME
        self.active_dibs = []

    @commands.Cog.listener()
    async def on_ready(self):
        if self.bot.db is None:
            self.bot.db = await asyncpg.create_pool(**POSTGRES)

        if self.channel is None:
            for guild in self.bot.guilds:
                ch = discord.utils.get(guild.text_channels, name="🏹hunting-zone")
                if ch:
                    self.channel = ch
                    print(f"[BOOT] HuntingZone channel: {self.channel.name}")
                    break

        await self.hunting_zone_embed()
        view = await ButtonsView.add_buttons(self)
        await self.channel.send(view=view)

    async def load_spots(self):
        async with self.bot.db.acquire() as conn:
            self.spots = await conn.fetch("SELECT * FROM spots")

    async def hunting_zone_embed(self):
        print("embed refresh")
        embed_window = discord.Embed(title="📋 Hunting Zone Status", color=0x4E5D94)
        name = "**Status:**"
        value = ""
        spot_list = []
        async with self.bot.db.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM dibs ORDER BY emoji")
            for row in rows:  # iterujemy po każdym duplikacie
                spot_name = row["spot_name"]
                if spot_name in spot_list:
                    continue
                emoji = row["emoji"]
                status = row["status"]
                cp_name = row["cp_name"]
                is_permanent = row["is_permanent"]
                dibs_end = row["dibs_end"]
                farm_end = row["farm_end"]
                if status == "free" and not is_permanent:
                    continue
                if not emoji:
                    continue
                if status == "free":
                    embed_status_part = "is free"
                elif status == "dibs":
                    embed_status_part = "on dibs ⌛"
                    # print(f"{spot_name} status is {status}")
                elif status == "taken":
                    # print(f"{spot_name} status is {status}")
                    embed_status_part = f"is taken by **{cp_name}** until <t:{farm_end}:t>(<t:{farm_end}:R>)"
                spot_list.append(spot_name)
                value += f"{emoji} **{spot_name}** {embed_status_part}\n"

        if value:  # dodajemy tylko jeśli coś mamy do pokazania
            embed_window.add_field(name=name, value=value, inline=False)
            if self.hunting_embed_msg:
                await self.hunting_embed_msg.edit(embed=embed_window)
            else:
                self.hunting_embed_msg = await self.channel.send(embed=embed_window)

class DibsView(discord.ui.View):
    def __init__(self, cog, spot, emoji, interaction):
        super().__init__(timeout=None)
        self.cog = cog
        self.bot = cog.bot
        self.channel = cog.channel
        self.spot = spot
        self.user = interaction.user
        self.user_name = interaction.user.display_name
        self.cp_name = self._get_cp_from_role()


    def _get_cp_from_role(self):
        for role in self.user.roles:
            if role.name not in excluded_roles and not role.name.startswith("@"):
                return role.name
        print(f"[ERROR] {self.user_name} have no cp name selected")
        return None

    async def dibs_start(self):
        if self.spot not in self.cog.active_dibs:
            print("new dibs")
            msg = await self.channel.send(f"{self.spot} dibs")
            print(msg)
            print(f"1st {self.cog.active_dibs}")
            self.cog.active_dibs = msg
            print(f"2nd {self.cog.active_dibs}")
        else:
            print(f"3nd {self.cog.active_dibs}")
            print("update dibs")

        print(f"{self.spot}, {self.user_name}, {self.cp_name}")


class ButtonsView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog
        self.bot = cog.bot
        self.channel = cog.channel
        self.cp_name = None


    @classmethod
    async def add_buttons(cls, cog):
        try:
            self = cls(cog)
            async with self.bot.db.acquire() as conn:
                rows = await conn.fetch("SELECT * FROM dibs ORDER BY emoji")
                for row in rows:
                    spot = row["spot_name"]
                    emoji = row["emoji"]
                    if not emoji:
                        continue

                    button = discord.ui.Button(
                        emoji=emoji,
                        style=discord.ButtonStyle.secondary,
                    )

                    async def callback(
                        interaction: discord.Interaction, spot=spot, emoji=emoji
                    ):
                        try:
                            await interaction.response.defer()
                            view = DibsView(cog, spot, emoji, interaction)
                            await view.dibs_start()
                        except Exception as e:
                            print(e)

                    button.callback = callback
                    self.add_item(button)
            return self
        except Exception as e:
            print(e)

    @discord.ui.button(label="Add spot", style=discord.ButtonStyle.green, row=4)
    async def add_spot(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        view = AddSpotView(self.cog)
        await interaction.response.defer()
        await interaction.followup.send(view=view, ephemeral=True)

    @discord.ui.button(label="message cache", style=discord.ButtonStyle.green, row=4)
    async def view_message_cache(self, interaction, button):
        await interaction.response.defer()
        print (self.bot.message_cache)

    @discord.ui.button(label="toggle roles", style=discord.ButtonStyle.green, row=4)
    async def toggle_role(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        user = interaction.user
        await interaction.response.defer(
            ephemeral=True
        )  # tylko potwierdzenie kliknięcia

        new_role = await self.toggle_cp_role(user)

    def get_cp_from_role(self, user: discord.Member):
        for role in user.roles:
            if role.name not in excluded_roles and not role.name.startswith("@"):

                return role.name

        return None

    async def toggle_cp_role(self, user: discord.Member):
        current_cp = self.get_cp_from_role(user)
        if not current_cp:
            return None

        if current_cp == "Union":
            new_role_name = "Keknervous"
        elif current_cp == "Keknervous":
            new_role_name = "Union"
        else:
            print(
                f"[DEBUG] toggle_cp_role: {user} ma inną rolę niż Union/Keknervous -> {current_cp}"
            )
            return None

        guild = user.guild
        new_role = discord.utils.get(guild.roles, name=new_role_name)
        old_role = discord.utils.get(guild.roles, name=current_cp)

        if not new_role or not old_role:

            return None

        await user.remove_roles(old_role)
        await user.add_roles(new_role)

        print(f"[DEBUG] {new_role_name}")
        return new_role.name

    @discord.ui.button(
        label="trigger test - stakato", style=discord.ButtonStyle.green, row=4
    )
    async def trigger_test(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        try:
            await interaction.response.defer()
            farm_end = int(time.time()) + 10
            async with self.bot.db.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE dibs
                    SET status = $1,
                        cp_name = $2,
                        farm_end = $3
                    WHERE spot_name = $4
                    """,
                    "taken",
                    "Union",
                    farm_end,
                    "Stakato",
                )

        except Exception as e:
            print(e)



# ===== SETUP FUNKCJA =====
async def setup(bot: commands.Bot):
    await bot.add_cog(Spots(bot))