import discord
from discord.ext import commands
import asyncpg
import asyncio
import dateparser
import time
from data.data_tod_report import boss_config, sides


from cogs.tools import Tools

# Globals
channel = None
boss_message_ref = None
tod_cache = []


class TodReport(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.door_time_after_window_start = None
        self.door_time_before_window_start = None

    @commands.Cog.listener()
    async def on_ready(self):

        """global db
        if db is None:
            db = await asyncpg.create_pool(**POSTGRES)"""

        global channel
        if channel is None:
            for guild in self.bot.guilds:
                ch = discord.utils.get(guild.text_channels, name="⏰tod-report")
                if ch:
                    channel = ch

                    break
        ######### DISABLER ############
		await channel.send("cog disabled")
		return
		######### DISABLER #############
        await asyncio.sleep(3)

        await self.tod_report_embed()

        await self.start()

    async def tod_report_embed(self):

        boss_windows = []
        await self.calculate_door_time()
        async with self.bot.db.acquire() as conn:

            for boss_name in boss_config:
                row = await conn.fetchrow(
                    """
                    SELECT boss_name, tod, killed_by, dropped, window_start, window_end, valid_report
                    FROM tods
                    WHERE boss_name = $1
                    ORDER BY tod DESC
                    LIMIT 1
                    """,
                    boss_name,
                )
                if row:
                    tod = row["tod"]
                    killed_by = row["killed_by"]
                    dropped = row["dropped"]
                    window_start = row["window_start"]
                    window_end = row["window_end"]
                    valid_report = row["valid_report"]
                else:
                    tod = 0
                    killed_by = None
                    dropped = None
                    window_start = 0
                    window_end = 0
                    valid_report = False

                boss_windows.append(
                    {
                        "boss_name": boss_name,
                        "tod": tod,
                        "killed_by": killed_by,
                        "dropped": dropped,
                        "window_start": window_start,
                        "window_end": window_end,
                        "valid_report": valid_report,
                    }
                )
        boss_windows.sort(key=lambda x: x["window_start"])
        embed_window = discord.Embed(title="⏰ BOSS WINDOWS ⏰", color=0x4E5D94)

        sorted_bosses = [
            b for b in boss_windows if not boss_config[b["boss_name"]]["epic"]
        ] + [b for b in boss_windows if boss_config[b["boss_name"]]["epic"]]

        for boss in sorted_bosses:
            line1 = []
            line2 = []

            if boss["tod"] == 0:
                line1.append("**TOD:** unknown")
            else:
                line1.append(f"**TOD:** <t:{boss['tod']}:f>")

            if boss["killed_by"]:
                line1.append(f"{boss['killed_by']}")
            if boss["boss_name"] == "Queen Ant":
                if boss["dropped"]:
                    line1.append("\n**DROP:** ✅")
                else:
                    line1.append("\n**DROP:** ❌")
            if boss["window_start"]:
                line2.append(
                    f"**NEXT:** <t:{boss['window_start']}:f> (<t:{boss['window_start']}:R>)"
                )
            if boss["window_end"]:
                line2.append(f"<t:{boss['window_end']}:t>")
            if boss["boss_name"] == "Zaken":
                line2.append(
                    f"\n**DOORS**: <t:{self.door_time_before_window_start}:t>, <t:{self.door_time_after_window_start}:t>"
                )
            if not boss["valid_report"]:
                line2 = ["TOD is not reported ⁉️"]

            value = " • ".join(line1)
            if line2:
                value += f"\n{' • '.join(line2)}"
            name = (
                f"👑 {boss['boss_name']}"
                if boss_config[boss["boss_name"]]["epic"]
                else boss["boss_name"]
            )
            embed_window.add_field(name=name, value=value, inline=False)

        global boss_message_ref
        if boss_message_ref:
            await boss_message_ref.edit(embed=embed_window)

        else:
            boss_message_ref = await channel.send(embed=embed_window)

    async def calculate_door_time(self):

        try:
            async with self.bot.db.acquire() as conn:
                door_time = await conn.fetchval("SELECT door_time FROM doors LIMIT 1")
                next_zaken_respawn_start = await conn.fetchval(
                    "SELECT window_start FROM tods WHERE boss_name = $1 ORDER BY window_start DESC LIMIT 1",
                    "Zaken",
                )
                if not door_time:
                    door_time = 0
            door_time = int(door_time)
            next_zaken_respawn_start = int(next_zaken_respawn_start)

        except Exception as e:
            print(e)

        now = int(time.time())
        four_hours = 4 * 60 * 60
        while True:
            door_time += four_hours
            if next_zaken_respawn_start - door_time < four_hours:
                self.door_time_before_window_start = door_time
                self.door_time_after_window_start = (
                    self.door_time_before_window_start + four_hours
                )
                break

        # return door_time_after_window_start

    async def start(self):
        await channel.send(view=ReportTodView(self))


class ReportTodView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog
        self.bot = cog.bot
        self.user_id = None
        self.timezone = None

    async def get_timezone(self):
        async with self.bot.db.acquire() as conn:
            result = await conn.fetchrow(
                "SELECT timezone FROM users WHERE user_id = $1", self.user_id
            )
        if result is None:
            return None
        return result["timezone"]

    @discord.ui.button(label="REPORT TOD", style=discord.ButtonStyle.green)
    async def report_tod(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        self.user_id = interaction.user.id
        self.timezone = await self.get_timezone()

        if self.timezone:
            await interaction.response.defer(ephemeral=True)
            view=SelectBossView(cog=self.cog, timezone=self.timezone)
            await interaction.followup.send("Choose boss:", view=view, ephemeral=True)
        else:
            await interaction.response.defer(ephemeral=True)
            await interaction.followup.send(
                "Select your timezone using 🌍\n It's required only once.",
                ephemeral=True,
            )
    @discord.ui.button(label="🚪", style=discord.ButtonStyle.grey)
    async def zaken_door(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        try:
            await interaction.response.send_modal(
                ZakenDoorModal(self.cog, view=self)
            )

            return
        except Exception as e:
            print(e)



    @discord.ui.button(label="🗒️", style=discord.ButtonStyle.grey)
    async def list_tod(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        view = ListTodView(self.cog)
        await interaction.response.defer(ephemeral=True)
        await interaction.followup.send(
            "Choose boss to see TODs:", view=view, ephemeral=True
        )

    @discord.ui.button(label="❌", style=discord.ButtonStyle.grey)
    async def delete_tod(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        view = DeleteTodView(self.cog)
        await interaction.response.defer(ephemeral=True)
        await interaction.followup.send(
            "Choose boss to delete TOD:", view=view, ephemeral=True
        )

    @discord.ui.button(label="🌍", style=discord.ButtonStyle.grey)
    async def timezone_setup(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        self.user_id = interaction.user.id
        self.timezone = await self.get_timezone()
        if self.timezone:
            try:
                async with self.bot.db.acquire() as conn:
                    await conn.execute(
                        "DELETE FROM users WHERE user_id = $1", self.user_id
                    )

            except Exception as e:
                print(f"[ERROR] {e}")

            await interaction.response.send_message(
                "❌ Your timezone has been deleted", ephemeral=True
            )
            return
        else:
            view = TimezoneView(self.cog)
            await interaction.response.defer(ephemeral=True)
            await interaction.followup.send(view=view, ephemeral=True)


class SelectBossView(discord.ui.View):
    def __init__(self, cog, timezone):
        super().__init__(timeout=60)
        self.username = None
        self.cog = cog
        self.bot = cog.bot
        self.timezone = timezone
        self.boss_selected = None
        self.is_epic = False
        self.side_selected = None
        self.drop_selected = None
        self.tod = int(time.time())
        self.epic_boss = [
            boss for boss, data in boss_config.items() if data.get("epic")
        ]

        # Buttons
        self.confirm_button = discord.ui.Button(
            label="Confirm", style=discord.ButtonStyle.green
        )
        self.confirm_button.callback = self.confirm_callback

        self.custom_button = discord.ui.Button(
            label="Edit Tod", style=discord.ButtonStyle.red
        )
        self.custom_button.callback = self.custom_callback

        self.yes_button = discord.ui.Button(
            label="Yes", style=discord.ButtonStyle.green
        )
        self.yes_button.callback = self.yes_callback

        self.no_button = discord.ui.Button(label="No", style=discord.ButtonStyle.red)
        self.no_button.callback = self.no_callback

        # Select Boss
        self.msg = self.boss_select = discord.ui.Select(
            placeholder="Choose boss",
            options=[
                discord.SelectOption(label=boss_name, value=boss_name)
                for boss_name in boss_config
            ],
            min_values=1,
            max_values=1,
        )
        self.boss_select.callback = self.boss_select_callback
        self.clear_items()
        self.add_item(self.boss_select)

        # Select side
        self.side_select = discord.ui.Select(
            placeholder="Choose side",
            options=[
                discord.SelectOption(label=key, value=value)
                for key, value in sides.items()
            ],
        )
        self.side_select.callback = self.side_select_callback

    async def on_timeout(self):
        pass

    def get_summary(self):
        parts = []
        if self.boss_selected:
            parts.append(f"Boss: **{self.boss_selected}**\n")
        if self.side_selected:
            parts.append(f"Killed by: **{self.side_selected}**\n")
        if self.drop_selected is not None:
            parts.append(f"Drop: **{'✅' if self.drop_selected else '❌'}**\n")
        if self.tod is None:
            parts.append("❌ Wrong TOD format, try again!")
            return "".join(parts)
        if self.tod > time.time():
            parts.append("❌ TOD from future, try again!")
            return "".join(parts)
        parts.append(f"TOD: <t:{self.tod}:F>\n")
        return "".join(parts)

    async def boss_select_callback(self, interaction: discord.Interaction):
        self.boss_selected = self.boss_select.values[0]
        self.clear_items()
        if self.boss_selected in self.epic_boss:
            self.is_epic = True
            self.add_item(self.side_select)
            await interaction.response.edit_message(content="Killed by:\n", view=self)
        else:
            self.add_item(self.confirm_button)
            self.add_item(self.custom_button)
            await interaction.response.edit_message(
                content=self.get_summary(), view=self
            )

    async def side_select_callback(self, interaction: discord.Interaction):
        self.side_selected = self.side_select.values[0]
        self.clear_items()

        if self.boss_selected == "Queen Ant":
            self.add_item(self.yes_button)
            self.add_item(self.no_button)
            await interaction.response.edit_message(content="Ring drop?\n", view=self)
        else:
            self.add_item(self.confirm_button)
            self.add_item(self.custom_button)
            await interaction.response.edit_message(
                content=self.get_summary(), view=self
            )

    async def yes_callback(self, interaction: discord.Interaction):
        self.drop_selected = True
        self.clear_items()
        self.add_item(self.confirm_button)
        self.add_item(self.custom_button)
        await interaction.response.edit_message(content=self.get_summary(), view=self)

    async def no_callback(self, interaction: discord.Interaction):
        self.drop_selected = False
        self.clear_items()
        self.add_item(self.confirm_button)
        self.add_item(self.custom_button)
        await interaction.response.edit_message(content=self.get_summary(), view=self)

    async def confirm_callback(self, interaction: discord.Interaction):
        try:
            await interaction.response.edit_message(
                content="✅ Reported, Thank You!", view=None
            )
        except Exception as e:
            print(f"ERROR] Delete failed: {e}")

        try:
            await self.save_to_db(interaction)
            self.username = interaction.user.display_name
            embed_summary = discord.Embed(title="⏰ TOD reported", color=0x37FF77)
            embed_summary.add_field(
                name="", value=f"{self.get_summary()}\nBy: **{self.username}**"
            )

            summary_msg = await interaction.channel.send(embed=embed_summary)
            asyncio.create_task(
                Tools.delete_later(TodReport, msg=summary_msg, delay=60)
            )
            print(f"[TOD] {self.boss_selected} reported by {interaction.user.display_name} as <t:{self.tod}:f>")

        except Exception as e:
            print(f"[ERROR] Send failed: {e}")

    async def custom_callback(self, interaction: discord.Interaction):
        self.clear_items()
        await interaction.response.send_modal(
            CustomTodModal(view=self, timezone=self.timezone)
        )

    async def save_to_db(self, interaction: discord.Interaction):
        window_start = self.tod + boss_config[self.boss_selected]["respawn"]
        window = boss_config[self.boss_selected]["window"]
        window_end = window_start + window
        username = interaction.user.display_name
        async with self.bot.db.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO tods (
                    boss_name,
                    epic,
                    killed_by,
                    reported_by,
                    tod,
                    dropped,
                    window_start,
                    window_end,
                    valid_report
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                """,
                self.boss_selected,
                self.is_epic,
                self.side_selected,
                username,
                self.tod,
                self.drop_selected,
                window_start,
                window_end,
                True,
            )
        record_to_cache = (self.boss_selected, window_end)
        tod_cache.append(record_to_cache)
        await self.cog.tod_report_embed()


    async def make_report_invalid(self, boss, window_end):
        async with self.bot.db.acquire() as conn:
            await conn.execute(
                "UPDATE tods SET valid_report = $1 WHERE boss_name = $2 AND window_end <= $3",
                False,
                boss,
                window_end,
            )
            await self.cog.tod_report_embed()
            tod_cache.remove((boss, window_end))
        print(f"[TOD] {boss} window ended, no report.")


    async def monitor_tod_cache(self):
        while True:
            async with self.bot.db.acquire() as conn:
                for boss in boss_config.keys():
                    row = await conn.fetchrow(
                        "SELECT window_end FROM tods WHERE boss_name = $1 AND valid_report = $2 ORDER BY window_end DESC LIMIT 1",
                        boss,
                        True,
                    )
                    if row is not None:
                        window_end = int(row[0])
                        record_to_cache = (boss, window_end)
                        tod_cache.append(record_to_cache)

            now = int(time.time())
            for boss, window_end in tod_cache[:]:
                if window_end < now:
                    await self.make_report_invalid(boss, window_end)

            await asyncio.sleep(120)


class DeleteTodView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=60)
        self.cog = cog
        self.bot = cog.bot
        self.boss_selected = None
        self.tod_select = None
        self.tod_list = []
        self.tod_list_msg = ""

        self.boss_select = discord.ui.Select(
            placeholder="Choose boss",
            options=[
                discord.SelectOption(label=boss_name, value=boss_name)
                for boss_name in boss_config
            ],
        )
        self.boss_select.callback = self.boss_select_callback
        self.add_item(self.boss_select)

    async def boss_select_callback(self, interaction: discord.Interaction):
        self.clear_items()
        self.boss_selected = self.boss_select.values[0]

        async with self.bot.db.acquire() as conn:  # type: asyncpg.Connection
            rows = await conn.fetch(
                "SELECT id, tod, reported_by FROM tods WHERE boss_name = $1",
                self.boss_selected,

            )
            if not rows:
                await interaction.response.edit_message(
                    content=f"No valid TODs for {self.boss_selected}", view=self
                )
                return
            for tod_id, tod, reported_by in rows:
                self.tod_list.append((tod_id, tod))
                line = f"{tod_id} - <t:{tod}:f> - {reported_by}\n"
                self.tod_list_msg += line

        self.tod_select = discord.ui.Select(
            placeholder="Wybierz TOD",
            options=[
                discord.SelectOption(label=str(tod_id), value=str(tod_id))
                for tod_id, tod in self.tod_list
            ],
        )

        self.tod_select.callback = self.tod_select_callback

        self.add_item(self.tod_select)

        await interaction.response.edit_message(
            content=f"{self.tod_list_msg}", view=self
        )

    async def tod_select_callback(self, interaction: discord.Interaction):

        selected_id = int(self.tod_select.values[0])

        selected_tod = next(
            tod for tod_id, tod in self.tod_list if tod_id == selected_id
        )

        async with self.bot.db.acquire() as conn:
            await conn.execute(
                "DELETE FROM tods WHERE id = $1",
                selected_id,
            )

        self.clear_items()
        await self.cog.tod_report_embed()

        print(
            f"[TOD] {interaction.user.display_name} manually deleted entry: {self.boss_selected} - <t:{selected_tod}:f>"
        )

        await interaction.response.edit_message(
            content=f"❌ Deleted TOD:\n**Boss:** {self.boss_selected}\n**TOD**: <t:{selected_tod}:f>",
            view=self,
        )


class ListTodView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=60)
        self.cog = cog
        self.bot = cog.bot
        self.boss_selected = None
        self.tod_list_msg = ""

        self.boss_select = discord.ui.Select(
            placeholder="Choose boss",
            options=[
                discord.SelectOption(label=boss_name, value=boss_name)
                for boss_name in boss_config
            ],
        )
        self.boss_select.callback = self.boss_select_callback
        self.add_item(self.boss_select)

    async def boss_select_callback(self, interaction: discord.Interaction):
        self.clear_items()
        self.boss_selected = self.boss_select.values[0]

        async with self.bot.db.acquire() as conn:  # type: asyncpg.Connection
            rows = await conn.fetch(
                "SELECT tod, reported_by, killed_by, dropped FROM tods WHERE boss_name = $1 ORDER BY tod DESC LIMIT 20",
                self.boss_selected,
            )
            if not rows:
                await interaction.response.edit_message(
                    content=f"No TOD data for {self.boss_selected}", view=self
                )
                return
            self.tod_list_msg += f"\n🗒️ Last 20 Tods for **{self.boss_selected}**\n\n"
            for row in rows[::-1]:
                tod_line = f"- <t:{row[0]}:f> (<t:{row[0]}:R>)"
                killed_by = f" - {row[2]}" if row[2] else ""
                drop_status = ""
                if self.boss_selected == "Queen Ant":
                    drop_status = " - ✅" if row[3] else " - ❌"
                reported_by = f" - {row[1]}"
                self.tod_list_msg += (
                    f"{tod_line}{drop_status}{killed_by}{reported_by}\n"
                )

        await interaction.response.edit_message(content=self.tod_list_msg, view=None)


class CustomTodModal(discord.ui.Modal, title="Enter Custom TOD"):
    def __init__(self, view: SelectBossView, timezone):
        super().__init__()
        self.view = view
        self.timezone = timezone
        self.tod_input = discord.ui.TextInput(
            label="Enter TOD:", placeholder="e.g 23:10, 25.05.2025 23:10 or yesterday 23:10", required=True
        )
        self.add_item(self.tod_input)

    async def parse_time(self):
        tod_str = self.tod_input.value

        tz = None
        if self.timezone:

            tz = self.timezone.split(" ")[-1]

        parsed = dateparser.parse(
            tod_str,
            settings={
                "TIMEZONE": tz,
                "TO_TIMEZONE": "UTC",
                "RETURN_AS_TIMEZONE_AWARE": True,
                "DATE_ORDER": "DMY",
            },
        )
        if parsed is None:

            return None
        return int(parsed.timestamp())

    async def on_submit(self, interaction: discord.Interaction):

        parsed_tod = await self.parse_time()
        self.view.tod = parsed_tod
        if parsed_tod is None:

            self.view.clear_items()
            self.view.add_item(self.view.custom_button)
            await interaction.response.edit_message(
                content=f"{self.view.get_summary()}\n Edited tod not recognised, try again",
                view=self.view,
            )
            return
        if parsed_tod > int(time.time()):

            self.view.clear_items()
            self.view.add_item(self.view.custom_button)
            await interaction.response.edit_message(
                content=f"{self.view.get_summary()}", view=self.view
            )
            return

        self.view.clear_items()
        if hasattr(self.view, "confirm_button"):
            self.view.add_item(self.view.confirm_button)
            self.view.add_item(self.view.custom_button)

            await interaction.response.edit_message(
                content=self.view.get_summary(), view=self.view
            )


class TimezoneView(discord.ui.View):
    def __init__(self, cog):
        self.cog = cog
        self.bot = cog.bot
        super().__init__(timeout=60)

        self.timezones = [
            "UTC-12:00 Etc/GMT+12",
            "UTC-11:00 Pacific/Midway",
            "UTC-10:00 Pacific/Honolulu",
            "UTC-09:00 America/Anchorage",
            "UTC-08:00 America/Los_Angeles",
            "UTC-07:00 America/Denver",
            "UTC-06:00 America/Chicago",
            "UTC-05:00 America/New_York",
            "UTC-04:00 America/Santiago",
            "UTC-03:00 America/Argentina/Buenos_Aires",
            "UTC-02:00 America/Noronha",
            "UTC-01:00 Atlantic/Azores",
            "UTC+00:00 UTC",
            "UTC+01:00 Europe/Berlin",
            "UTC+02:00 Europe/Kyiv",
            "UTC+03:00 Europe/Moscow",
            "UTC+04:00 Asia/Dubai",
            "UTC+05:00 Asia/Karachi",
            "UTC+06:00 Asia/Dhaka",
            "UTC+07:00 Asia/Bangkok",
            "UTC+08:00 Asia/Shanghai",
            "UTC+09:00 Asia/Tokyo",
            "UTC+10:00 Australia/Sydney",
            "UTC+11:00 Pacific/Guadalcanal",
            "UTC+12:00 Pacific/Auckland",
        ]

        self.timezone_select = discord.ui.Select(
            placeholder="Select your timezone...",
            min_values=1,
            max_values=1,
            options=[discord.SelectOption(label=tz, value=tz) for tz in self.timezones],
        )

        self.timezone_select.callback = self.timezone_select_callback
        self.add_item(self.timezone_select)

    async def timezone_select_callback(self, interaction: discord.Interaction):

        user_id = interaction.user.id
        username = interaction.user.display_name
        selected_timezone = self.timezone_select.values[0]

        try:

            async with self.bot.db.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO users (user_id, username, timezone)
                    VALUES ($1, $2, $3)
                    ON CONFLICT (user_id)
                    DO UPDATE SET username = $2, timezone = $3
                    """,
                    user_id,
                    username,
                    selected_timezone,
                )

        except Exception as e:
            print("[ERROR]", e)

        self.clear_items()
        await interaction.response.edit_message(
            content=f"✅ Timezone selected: `{selected_timezone}`", view=self
        )


class ZakenDoorModal(discord.ui.Modal, title="Zaken door calculator"):
    def __init__(self,cog, view):
        super().__init__()
        self.cog = cog
        self.bot = cog.bot
        self.view = view
        self.time_ig_input = discord.ui.TextInput(
            label="Enter IN-GAME time", placeholder="e.g. 23:10", required=True
        )
        self.add_item(self.time_ig_input)

    async def on_submit(self, interaction: discord.Interaction):
        now = int(time.time())
        print(f"[DOOR] {interaction.user.display_name} reported door as {self.time_ig_input} ig")
        await interaction.response.defer()
        time_ig = str(self.time_ig_input)
        try:
            hh, mm = map(int, time_ig.split(":"))
        except:
            await interaction.followup.send("❌ Wrong input, try again.\nRemember to use **IN GAME** hh:mm format", ephemeral=True)
        if hh > 23 or mm > 59:
            await interaction.followup.send("❌ Wrong ig-time format, try again.", ephemeral=True)
            return
        # print(hh)
        # print(mm)
        time_since_last_door = int((hh * 60 * 10) + (mm * 10))
        # print(time_since_last_door)
        door_time = int(now - time_since_last_door)
        await interaction.followup.send(
            f"🚪 Last Zaken door: <t:{door_time}:t>", ephemeral=True
        )
        try:
            async with self.bot.db.acquire() as conn:
                await conn.execute("UPDATE doors SET door_time = $1", door_time)
        except Exception as e:
            print(e)
        try:
            await self.cog.tod_report_embed()
        except Exception as e:
            print(e)
        return


async def setup(bot: commands.Bot):
    await bot.add_cog(TodReport(bot))
