import discord
from discord.ext import commands
from discord import app_commands
import logging
import os
import asyncio
import time
import sys
import inspect
from typing import Callable

# ===================== Cog =====================

class Tools(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

        # Logger globalny
        self.bot.logger = logging.getLogger("niobot")
        self.bot.logger.setLevel(logging.DEBUG)
        file_handler = logging.FileHandler("log.log", encoding="utf-8")
        file_formatter = DiscordTimestampFormatter("%(discord_time)s %(message)s")
        file_handler.setFormatter(file_formatter)
        self.bot.logger.addHandler(file_handler)

        # Przekierowanie stdout i stderr
        sys.stdout = PrintToLogger(self.bot.logger.info, sys.__stdout__)
        sys.stderr = PrintToLogger(self.bot.logger.error, sys.__stderr__)

        # TaskManager i MessageCache
        self.task_manager = TaskManager()
        self.bot.task_manager = self.task_manager
        self.message_cache = MessageCache()
        self.bot.message_cache = self.message_cache

    @commands.Cog.listener()
    async def on_ready(self):
        await self.clear_channels()

    async def clear_channels(self):
        #for channel_name in ["⏰tod-report"]:
        for channel_name in ["🏹hunting-zone", "⏰tod-report"]:
            channel = discord.utils.get(self.bot.get_all_channels(), name=channel_name)
            if channel:
                async for message in channel.history(limit=100):
                    try:
                        await message.delete()
                        print(f"[LOG] {message.id} message deleted")
                    except discord.Forbidden:
                        print("[ERROR] Brak uprawnień do usuwania wiadomości.")
                    except discord.HTTPException as e:
                        print(f"[ERROR] Błąd przy usuwaniu wiadomości: {e}")
            else:
                print(f"[ERROR] Kanał {channel_name} nie został znaleziony.")

    @staticmethod
    def is_admin():
        async def predicate(interaction: discord.Interaction) -> bool:
            return interaction.user.guild_permissions.administrator
        return app_commands.check(predicate)

    @app_commands.command(name="reboot", description="Bot reboot, admin only")
    @is_admin()
    async def reboot(self, interaction: discord.Interaction):
        await interaction.response.send_message("Rebooting...", ephemeral=True)
        print(f"[LOG] {interaction.user.display_name} rebooted Niobot 2.0")
        await self.bot.close()
        os._exit(0)

    async def delete_later(self, msg, delay):
        await asyncio.sleep(delay)
        await msg.delete()

# ===================== Helper Classes =====================

class DiscordTimestampFormatter(logging.Formatter):
    def format(self, record):
        record.discord_time = f"<t:{int(time.time())}:t>"
        return super().format(record)

class PrintToLogger:
    def __init__(self, logger_func, original):
        self.logger_func = logger_func
        self.original = original
        self._buffer = ""

    def write(self, message):
        self.original.write(message)
        self._buffer += message
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            if line.strip():
                self.logger_func(line.strip())

    def flush(self):
        self.original.flush()
        if self._buffer.strip():
            self.logger_func(self._buffer.strip())
            self._buffer = ""

class MessageCache:
    def __init__(self):
        self._cache: dict[int, discord.Message] = {}  # message_id → Message

    def add(self, message: discord.Message):
        self._cache[message.id] = message

    def get_id(self, message_id: int) -> discord.Message | None:
        return self._cache.get(message_id)

    def get_message(self, spot: str) -> discord.Message | None:
        for msg in self._cache.values():
            for embed in msg.embeds:
                if embed.title and spot in embed.title:
                    return msg
        return None

    def remove(self, message_id: int):
        self._cache.pop(message_id, None)
        print(f"{message_id} removed via tools")

    def clear(self):
        self._cache.clear()

    def all(self) -> list[discord.Message]:
        return list(self._cache.values())

    def __repr__(self):
        lines = []
        for msg in self._cache.values():
            title = msg.embeds[0].title if msg.embeds else msg.content
            lines.append(f"{msg.id}: '{title}' (#{msg.channel.name})")
        return "\n".join(lines) or "<empty cache>"

class TaskManager:
    def __init__(self):
        self.tasks: dict[str, asyncio.Task] = {}

    async def _job(self, name: str, delay: int, func: Callable, *args, **kwargs):
        if delay > 0:
            await asyncio.sleep(delay)
        try:
            if inspect.iscoroutinefunction(func):
                await func(*args, **kwargs)  # async function
            else:
                func(*args, **kwargs)        # normal function
            print(f"✅ Task {name} wykonany")
        except asyncio.CancelledError:
            print(f"❌ Task {name} anulowany")
            raise
        finally:
            self.tasks.pop(name, None)

    def add(self, name: str, delay: int, func: Callable, *args, **kwargs):
        if name in self.tasks:
            print(f"⚠️ Task {name} już istnieje")
            return
        task = asyncio.create_task(self._job(name, delay, func,*args, **kwargs))
        self.tasks[name] = task
        print(f"[TASK] dodano {name}")

    async def cancel(self, name: str):
        try:
            task = self.tasks.get(name)
            if task:
                task.cancel()
                # teraz task zakończony – możemy usunąć ze słownika
                self.tasks.pop(name, None)
                print(f"[TASK] {name} canceled")
            else:
                print(f"⚠️ Brak taska {name}")
        except Exception as e:
            print(f"TaskManager delete error:\n{e}")

    def view_all(self):
        if self.tasks:
            print("Active tasks:")
            for name in self.tasks:
                print(f"- {name}")
        else:
            print("No active tasks.")



# ===================== SETUP =====================

async def setup(bot: commands.Bot):
    await bot.add_cog(Tools(bot))