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


# ===== Cog główny =====
class HuntingZone(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.bot.db = None
        self.channel = None
        self.hunting_embed_msg = None
        self.letters_emoji = letter_emojis
        self.dibs_time = DIBS_TIME
        self.farm_time = FARM_TIME
        self.blacklist_time = BLACKLIST_TIME
        self.global_blacklist_time = GLOBAL_BLACKLIST_TIME
        self.buttons_view = ButtonsView(self)
        self.spots = None
        self.finalize_dibs_instance = FinalizeDibs(self)

    @commands.Cog.listener()
    async def on_ready(self):
        #print("hunting_zone_no_cache disabled")
        #return ############################################## WYŁĄCZNIK ####################################################
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
        asyncio.create_task(self.load_spots())

        # Trigger tworzymy w __init__
        asyncio.create_task(self.setup_triggers())
        # Pętla czyszcząca też w __init__
        asyncio.create_task(self.cleanup_loop())

    async def setup_triggers(self):
        async with self.bot.db.acquire() as conn:
            await conn.execute(
                """
               CREATE OR REPLACE FUNCTION cleanup_and_rebuild_dibs()
               RETURNS TRIGGER AS $$
               BEGIN
                   DELETE FROM dibs
                   WHERE spot_name = NEW.spot_name
                     AND cp_name != NEW.cp_name;

                   DELETE FROM dibs
                   WHERE cp_name = NEW.cp_name
                     AND spot_name != NEW.spot_name;

                   INSERT INTO dibs (spot_name, emoji, is_permanent)
                   SELECT s.spot_name, s.emoji, s.is_permanent
                   FROM spots s
                   WHERE NOT EXISTS (
                       SELECT 1 FROM dibs d WHERE d.spot_name = s.spot_name
                   );

                   RETURN NEW;
               END;
               $$ LANGUAGE plpgsql;

               CREATE OR REPLACE TRIGGER trg_cleanup_and_rebuild_dibs
               AFTER UPDATE OF status ON dibs
               FOR EACH ROW
               WHEN (NEW.status = 'taken')
            
               EXECUTE FUNCTION cleanup_and_rebuild_dibs();
               """
            )

            await conn.execute(
                """CREATE OR REPLACE FUNCTION rebuild_dibs_if_all_free()
                    RETURNS void AS $$
                    DECLARE
                        all_free BOOLEAN;
                    BEGIN
                        -- sprawdzamy, czy wszystkie statusy to 'free'
                        SELECT bool_and(status = 'free') INTO all_free FROM dibs;
                    
                        IF all_free THEN
                            -- czyścimy tabelę i restartujemy ID
                            EXECUTE 'TRUNCATE TABLE dibs RESTART IDENTITY';
                    
                            -- odbudowujemy wpisy z tabeli spots
                            EXECUTE '
                                INSERT INTO dibs (spot_name, emoji, is_permanent)
                                SELECT s.spot_name, s.emoji, s.is_permanent
                                FROM spots s
                                WHERE NOT EXISTS (
                                    SELECT 1 FROM dibs d WHERE d.spot_name = s.spot_name
                                )
                            ';
                        END IF;
                    END;
                    $$ LANGUAGE plpgsql;
                    """
            )

    async def cleanup_loop(self):
        while True:
            now = int(time.time())
            async with self.bot.db.acquire() as conn:
                # 1. Usuń przeterminowane dibsy i farmy
                result_dibs = await conn.execute(
                    """
                    DELETE FROM dibs
                    WHERE status = $1 AND dibs_end > $2 AND dibs_end < $3
                """,
                    "dibs",
                    0,
                    now,
                )
                result_farm = await conn.execute(
                    """
                    DELETE FROM dibs
                    WHERE farm_end < $2 AND farm_end > $1
                """,
                    0,
                    now,
                )

                # Sprawdzenie ile rekordów zostało zmienionych
                changes = 0
                # asyncpg zwraca np. 'DELETE 3'
                if result_dibs.startswith("DELETE"):
                    changes += int(result_dibs.split()[1])
                if result_farm.startswith("DELETE"):
                    changes += int(result_farm.split()[1])

                # 2. Rebuild brakujących rekordów
                rebuild_result = await conn.execute(
                    """
                    INSERT INTO dibs (spot_name, emoji, is_permanent)
                    SELECT s.spot_name, s.emoji, s.is_permanent
                    FROM spots s
                    WHERE NOT EXISTS (
                        SELECT 1 FROM dibs d WHERE d.spot_name = s.spot_name
                    )
                """
                )
                if rebuild_result.startswith("INSERT"):
                    changes += int(rebuild_result.split()[1])

            # 3. Feedback – jeśli coś się zmieniło, np. aktualizuj view
            if changes > 0:
                # tu wywołujesz swoją funkcję do edycji view
                await self.hunting_zone_embed()
                print(f"{changes=}")  # przykładowa funkcja, masz już gotową część

            await asyncio.sleep(30)  # np. co 5 minut

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
                    #print(f"{spot_name} status is {status}")
                elif status == "taken":
                    #print(f"{spot_name} status is {status}")
                    embed_status_part = f"is taken by **{cp_name}** until <t:{farm_end}:t>(<t:{farm_end}:R>)"
                spot_list.append(spot_name)
                value += f"{emoji} **{spot_name}** {embed_status_part}\n"

        if value:  # dodajemy tylko jeśli coś mamy do pokazania
            embed_window.add_field(name=name, value=value, inline=False)
            if self.hunting_embed_msg:
                await self.hunting_embed_msg.edit(embed=embed_window)
            else:
                self.hunting_embed_msg = await self.channel.send(embed=embed_window)


# ===== Podklasy poza coga =====
class DibsView(discord.ui.View):
    def __init__(self, cog, spot, emoji):
        super().__init__(timeout=None)
        self.cog = cog
        self.bot = cog.bot
        self.channel = cog.channel
        self.msg = None
        self.spot = spot
        self.emoji = emoji
        self.dibs_start_time = int(time.time())
        self.dibs_end_time = self.dibs_start_time + self.cog.dibs_time
        self.cp_name = None
        self.priority = None

    def get_cp_from_role(self, user):
        for role in user.roles:
            if role.name not in excluded_roles and not role.name.startswith("@"):
                self.cp_name = role.name
                break
        return self.cp_name

    async def check_dibs(self, spot, interaction):
        """Sprawdza, czy cp_name ma już 'dibs' dla podanego spotu."""
        async with self.bot.db.acquire() as conn:
            row = await conn.fetchval(
                """
                SELECT 1 FROM dibs
                WHERE cp_name = $1
                  AND spot_name = $2
                  AND status = 'dibs'
                LIMIT 1
                """,
                self.cp_name,
                spot,
            )
            if row:
                await interaction.followup.send(
                    content=f"❌ {self.cp_name} already dibs for `{spot}`",
                    ephemeral=True,
                )
                return False
        return True

    async def check_taken(self, interaction):
        """Sprawdza, czy cp_name ma już 'taken' dla podanego spotu."""
        async with self.bot.db.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT 1 FROM dibs
                WHERE cp_name = $1
                  AND status = 'taken'
                LIMIT 1
                """,
                self.cp_name,
            )
            if row:
                await interaction.followup.send(
                    content=f"❌ {self.cp_name} already claimed a spot.",
                    ephemeral=True,
                )
                return False
        return True

    async def dibs_start(self, spot, interaction: discord.Interaction):
        self.get_cp_from_role(interaction.user)
        if await self.check_taken(interaction):
            if await self.check_dibs(spot, interaction):
                async with self.bot.db.acquire() as conn:
                    self.priority = await conn.fetchval(
                        "SELECT priority FROM cp_list WHERE cp_name = $1",
                        self.cp_name,
                    )
                name = self.cp_name
                value = (
                    f"Priority: {self.priority}\nby: {interaction.user.display_name}"
                )
                self.msg = self.bot.message_cache.get_message(self.spot)
                embed = discord.Embed(
                    title=f"🎯 Dibs in progress for {self.emoji} {self.spot}",
                    description=f"⏳ Results in <t:{self.dibs_end_time}:R>",
                    color=discord.Color.green(),
                )
                embed.add_field(name=name, value=value, inline=True)
                if self.msg:
                    # Kopia pierwszego embedu (oryginał jest immutable)
                    embed = self.msg.embeds[0].copy()
                    # Dodajemy nowe pole
                    embed.add_field(name=name, value=value, inline=True)
                    await self.msg.edit(embed=embed)
                else:
                    self.msg = await self.channel.send(embed=embed)
                    self.bot.message_cache.add(self.msg)
                    self.bot.task_manager.add(
                        name=f"{self.spot}",
                        delay=self.cog.dibs_time,
                        func=self.wait_and_finalize_dibs,
                        interaction=interaction,
                    )
                await self.db_add_dibs()
            await self.cog.hunting_zone_embed()

    async def wait_and_finalize_dibs(self, interaction):
        if await self.check_taken(interaction):
            await self.cog.finalize_dibs_instance.finalize_dibs(
                self.msg, self.emoji, self.spot
            )

    async def db_add_dibs(self):
        async with self.bot.db.acquire() as conn:
            dibs_started = await conn.fetchval(
                "SELECT cp_name FROM dibs WHERE spot_name = $1", self.spot
            )
            if not dibs_started:
                # print("update dibs")
                await conn.execute(
                    """
                    UPDATE dibs
                    SET status = $1,
                        cp_name = $2,
                        priority = $3,
                        message_id = $4,
                        dibs_start = $5,
                        dibs_end = $6
                    WHERE spot_name = $7
                    """,
                    "dibs",
                    self.cp_name,
                    self.priority,
                    self.msg.id,
                    self.dibs_start_time,
                    self.dibs_end_time,
                    self.spot,
                )
            else:
                # print("insert dibs")
                await conn.execute(
                    """
                    INSERT INTO dibs (status, cp_name, priority, message_id, dibs_start, dibs_end, spot_name, emoji)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
                    """,
                    "dibs",
                    self.cp_name,
                    self.priority,
                    self.msg.id,
                    self.dibs_start_time,
                    self.dibs_end_time,
                    self.spot,
                    self.emoji,
                )


# -----FinalizeDibs------#
class FinalizeDibs:
    def __init__(self, cog):
        self.cog = cog
        self.bot = cog.bot
        self.channel = cog.channel

    async def finalize_dibs(self, msg, emoji, spot):
        async with self.bot.db.acquire() as conn:
            farm_end = int(time.time()) + self.cog.farm_time
            winner_cp = await conn.fetchval(
                "SELECT cp_name FROM dibs WHERE spot_name = $1 ORDER BY priority ASC LIMIT 1",
                spot,
            )

        win_embed = discord.Embed(
            title=f"🎯 Dibs finished for {emoji} {spot}",
            description=f"🏆 Winer is **{winner_cp}**",
            color=discord.Color.gold(),
        )
        if msg.embeds:
            embed = msg.embeds[0]
            for field in embed.fields:
                win_embed.add_field(name=field.name, value=field.value, inline=True)
        winner_msg = await msg.edit(embed=win_embed)
        # await self.rebuild_dibs_db(spot)
        await self.rebuild_dibs(cp_name=winner_cp)
        self.bot.message_cache.remove(msg.id)

        print(winner_cp, emoji, spot)
        async with self.bot.db.acquire() as conn:
            if winner_cp:
                print("update to taken")
                await conn.execute(
                    """
                    UPDATE dibs
                    SET status = $1, farm_end = $2
                    WHERE spot_name = $3 AND cp_name = $4
                    """,
                    "taken",
                    farm_end,
                    spot,
                    winner_cp,
                )
        asyncio.create_task(self.set_spot_free(spot))
        asyncio.create_task(Tools.delete_later(self, winner_msg, 5))
        await self.cog.hunting_zone_embed()



    async def rebuild_dibs(self, cp_name):
        try:
            async with self.bot.db.acquire() as conn:
                rows = await conn.fetch("SELECT * FROM dibs")
                for row in rows:
                    spot = row["spot_name"]
                    message_id = row["message_id"]
                    status = row["status"]
                    dibs_cp_name = row["cp_name"]
                    if status == "free":
                        continue
                    print(f"{status} - {dibs_cp_name} / {cp_name}")
                    if status == "dibs" and dibs_cp_name == cp_name:
                        msg = self.bot.message_cache.get_message(spot)
                        existing_embed = msg.embeds[0]
                        embed = existing_embed
                        fields = [f for f in embed.fields if f.name != cp_name]
                        print(f"fields: {fields}")
                        new_embed = discord.Embed(
                            title=embed.title,
                            description=embed.description,
                            colour=embed.colour,
                        )
                        for f in fields:
                            new_embed.add_field(
                                name=f.name, value=f.value, inline=f.inline
                            )
                        if fields:
                            await msg.edit(embed=new_embed)
                        else:
                            await self.bot.task_manager.cancel(spot)
                            self.bot.message_cache.remove(msg.id)
                            await msg.delete()

        except Exception as e:
            print(f"message cache error - {e}")

    async def set_spot_free(self, spot):
        #print(f"set spot free wait start - {self.cog.farm_time} sec")
        await asyncio.sleep(self.cog.farm_time)
        #print("set spot free wait end")

        async with self.bot.db.acquire() as conn:
            await conn.execute("DELETE FROM dibs WHERE spot_name=$1", spot)
            await conn.execute(
                """
                INSERT INTO dibs (spot_name, emoji, is_permanent)
                SELECT s.spot_name, s.emoji, s.is_permanent
                FROM spots s
                WHERE NOT EXISTS (
                    SELECT 1 FROM dibs d WHERE d.spot_name = s.spot_name
                )
            """
            )
            result = await conn.fetchval("SELECT rebuild_dibs_if_all_free()")
            print(f"rebuild trigger result - {result}")

        await self.cog.hunting_zone_embed()


class AddSpotView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog
        self.bot = cog.bot
        self.letter_emojis = letter_emojis
        self.select_callback.options = self.build_options()

    def build_options(self):
        options = []
        try:
            for spot in self.cog.spots:
                spot_name = spot["spot_name"]
                is_perma = spot["is_permanent"]
                if not is_perma:
                    options.append(
                        discord.SelectOption(label=spot_name, value=spot_name)
                    )
        except Exception as e:
            print(e)
        return sorted(options, key=lambda r: r.label)

    @discord.ui.select(
        placeholder="Choose spot...",
        min_values=1,
        max_values=1,
        options=[],
    )
    async def select_callback(
        self, interaction: discord.Interaction, select: discord.ui.Select
    ):
        self.clear_items()
        spot = select.values[0]
        emoji = self.letter_emojis.pop(0)
        async with self.bot.db.acquire() as conn:
            await conn.execute(
                "UPDATE dibs SET emoji = $1 WHERE spot_name = $2", emoji, spot
            )
        try:
            await interaction.response.edit_message(
                content=f"You added {emoji} {spot}", view=self
            )
        except discord.errors.HTTPException as e:
            print(f"Nie udało się usunąć wiadomości z Selectem: {e}")
        view = DibsView(self.cog, spot, emoji)
        await view.dibs_start(spot, interaction)


class ButtonsView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog
        self.bot = cog.bot
        self.channel = cog.channel
        self.cp_name = None

    @classmethod
    async def add_buttons(cls, cog):
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
                        view = DibsView(cog, spot, emoji)
                        await view.dibs_start(spot, interaction)
                    except Exception as e:
                        print(e)

                button.callback = callback
                self.add_item(button)

        return self

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
    await bot.add_cog(HuntingZone(bot))
