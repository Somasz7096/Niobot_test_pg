import discord
from discord.ext import commands
import asyncio
import time
import asyncpg
from cogs.tools import Tools
from data.data_hunting_zone import letter_emojis, excluded_roles
from config import DIBS_TIME, FARM_TIME, BLACKLIST_TIME, GLOBAL_BLACKLIST_TIME
from mysecrets import POSTGRES
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)
active_dibs = []


class Spots(commands.Cog):
    def __init__(self, bot):
        self.now = int(time.time())
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

    @commands.Cog.listener()
    async def on_ready(self):
        # print("dibs_test disabled")
        # return ############################################## WYŁĄCZNIK ###################################################
        if self.bot.db is None:
            self.bot.db = await asyncpg.create_pool(**POSTGRES)

        if self.channel is None:
            for guild in self.bot.guilds:
                ch = discord.utils.get(guild.text_channels, name="🏹hunting-zone")
                if ch:
                    self.channel = ch
                    print(f"[BOOT] HuntingZone channel: {self.channel.name}")
                    break
        await self.channel.send("✅ dibs test cog active")
        await self.rebuild_dibs()
        await self.hunting_zone_embed()
        view = await ButtonsView.add_buttons(self)
        await self.channel.send(view=view)

    async def rebuild_dibs(self):
        try:
            async with self.bot.db.acquire() as conn:
                await conn.execute("DELETE FROM dibs WHERE farm_end < $1", self.now)
                await conn.execute(
                    """INSERT INTO dibs (spot_name, emoji, is_permanent)
                       SELECT s.spot_name, s.emoji, s.is_permanent
                       FROM spots s
                       WHERE NOT EXISTS (
                           SELECT 1 FROM dibs d WHERE d.spot_name = s.spot_name
                       );"""
                )
            print("[BOOT] dibs rebuilt")
        except Exception as e:
            print(f"dibs not rebuilt {e}")

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
        self.now = int(time.time())
        self.cog = cog
        self.bot = cog.bot
        self.channel = cog.channel
        self.spot = spot
        self.emoji = emoji
        self.interaction = interaction
        self.user = interaction.user
        self.user_name = interaction.user.display_name
        self.cp_name = self._get_cp_from_role()
        self.priority = None
        self.status = None
        self.dibs_end = None

    def _get_cp_from_role(self):
        for role in self.user.roles:
            if role.name not in excluded_roles and not role.name.startswith("@"):
                return role.name
        print(f"[ERROR] {self.user_name} have no cp name selected")
        return None

    async def _get_priority(self):
        async with self.bot.db.acquire() as conn:
            self.priority = await conn.fetchval(
                "SELECT priority FROM cp_list WHERE cp_name = $1", self.cp_name
            )

    async def _get_status(self):
        async with self.bot.db.acquire() as conn:
            dibs_status = await conn.fetchrow(
                "SELECT * FROM dibs WHERE spot_name = $1", self.spot
            )
            self.status = dibs_status["status"]
            self.dibs_end_time = dibs_status["dibs_end"]

    async def _send_dib_embed(self):
        embed = discord.Embed(
            title=f"🎯 Dibs in progress for `{self.emoji} {self.spot}`",
            description=f"⏳ Results in <t:{self.dibs_end}:R>",
            color=discord.Color.green(),
        )
        name = self.cp_name
        value = f"Priority: {self.priority}\nby: {self.user_name}"
        embed.add_field(name=name, value=value, inline=True)
        msg = await self.channel.send(embed=embed)
        return msg.id

    async def _edit_dib_embed(self):
        async with self.bot.db.acquire() as conn:
            msg_id = await conn.fetchval(
                "SELECT message_id FROM dibs WHERE spot_name = $1", self.spot
            )
            msg = await self.channel.fetch_message(msg_id)
            name = self.cp_name
            value = f"Priority: {self.priority}\nby: {self.user_name}"
            embed = msg.embeds[0]
            # Sprawdzenie, czy pole już istnieje
            if any(field.name == name for field in embed.fields):
                print(f"{self.cp_name} already dibs for {self.spot}")
                await self.interaction.followup.send(f"❌ {self.cp_name} already dibs for `{self.emoji} {self.spot}`", ephemeral=True)
                return
            embed.add_field(name=name, value=value, inline=True)
            await msg.edit(embed=embed)

    async def _db_followup_dibs(self):
        async with self.bot.db.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO dibs (spot_name, status, cp_name, priority)
                VALUES ($1, $2, $3, $4)
                """,
                self.spot,
                "dibs",
                self.cp_name,
                self.priority
            )
            print(f"{self.cp_name} added to {self.spot} dibs")

    async def _db_new_dibs(self, msg_id):
        async with self.bot.db.acquire() as conn:
            await conn.execute(
                """UPDATE dibs SET status = $1, cp_name = $2, priority = $3, message_id = $4, dibs_start = $5, dibs_end = $6 WHERE spot_name = $7""",
                "dibs",
                self.cp_name,
                self.priority,
                msg_id,
                self.now,
                self.dibs_end,
                self.spot,
            )
            print(f"{self.spot} status updated to dibs")

    async def _wait_and_finalize_dibs(self, msg_id):
        await asyncio.sleep(DIBS_TIME)
        async with self.bot.db.acquire() as conn:
            winner_cp = await conn.fetchval("SELECT cp_name FROM dibs WHERE spot_name = $1 ORDER BY priority ASC LIMIT 1", self.spot)
            print(f"{winner_cp=}")
        msg = await self.channel.fetch_message(msg_id)
        win_embed = discord.Embed(
            title=f"🎯 Dibs finished for `{self.emoji} {self.spot}`",
            description=f"🏆 Winer is **{winner_cp}**",
            color=discord.Color.gold(),
        )
        if msg.embeds:
            embed = msg.embeds[0]
            for field in embed.fields:
                win_embed.add_field(name=field.name, value=field.value, inline=True)
        winner_msg = await msg.edit(embed=win_embed)
        asyncio.create_task(Tools.delete_later(self, winner_msg, 20))
        async with self.bot.db.acquire() as conn:
            farm_end = int(time.time()) + FARM_TIME
            await conn.execute("UPDATE dibs SET status = $1, cp_name = $2, farm_end = $3 WHERE spot_name = $4", "taken", winner_cp, farm_end, self.spot)
        await self.cog.hunting_zone_embed()
        await self._set_spot_free()

    async def _set_spot_free(self):
        await asyncio.sleep(FARM_TIME)
        async with self.bot.db.acquire() as conn:
            await conn.execute("DELETE FROM dibs WHERE spot_name = $1", self.spot)
            await self.cog.rebuild_dibs()
            await self.cog.hunting_zone_embed()
            print(f"{self.spot} is free.")

    async def dibs_start(self):
        await self._get_priority()
        await self._get_status()
        if self.status == "free":
            print("new dibs")
            self.dibs_end = self.now + DIBS_TIME
            msg_id = await self._send_dib_embed()
            print(msg_id)
            await self._db_new_dibs(msg_id)
            await self.cog.hunting_zone_embed()
            await self._wait_and_finalize_dibs(msg_id)

        elif self.status == "dibs":
            print("update dibs")
            await self._db_followup_dibs()
            await self._edit_dib_embed()

        elif self.status == "taken":
            await self.interaction.followup.send(f"❌ `{self.emoji} {self.spot}` is already taken.", ephemeral=True)

        print(
            f"{self.spot}[{self.status}], {self.user_name} - {self.cp_name}[{self.priority}]"
        )


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
        print(self.bot.message_cache)

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
