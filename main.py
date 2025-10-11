import discord
from discord.ext import commands
import asyncio
import os
import subprocess
import sys
from config import DISCORD_TOKEN


intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.reactions = True
bot = commands.Bot(command_prefix="!", intents=intents)

def install_requirements():
    requirements_file = os.path.join(os.path.dirname(__file__), 'requirements.txt')
    if os.path.exists(requirements_file):
        print("📦 Installing requirements...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", requirements_file])
    else:
        print("⚠️ No requirements.txt found")

install_requirements()

async def main():
    await load_cogs()  # ładowanie cogów
    # Start bota
    await bot.start(DISCORD_TOKEN)

    # Czekamy aż bot będzie gotowy
    await bot.wait_until_ready()

    # Tutaj bezpiecznie można korzystać z API bota
    tools_cog = bot.get_cog("Tools")
    if tools_cog:
        await tools_cog.clear_channels()  # np. czyszczenie kanałów

    # Synchronizacja slash komend
    await bot.tree.sync()

    # Czekamy na zakończenie bota
    await bot_task

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
    await interaction.response.send_message(f"❌ Błąd: {error}", ephemeral=True)
    logging.error(f"[ERROR] Slash Error: {error}")

async def load_cogs():
    try:
        for filename in os.listdir("./niobot_pg/cogs"):
            if filename.endswith(".py"):
                try:
                    await bot.load_extension(f"cogs.{filename[:-3]}")
                    print(f"[BOOT] 📦 Załadowano cog: {filename}")
                except Exception as e:
                    print(f"[ERROR] Nie można załadować {filename}: {e}")
    except:
        for filename in os.listdir("./cogs"):
            if filename.endswith(".py"):
                try:
                    await bot.load_extension(f"cogs.{filename[:-3]}")
                    print(f"[BOOT] 📦 Załadowano cog: {filename}")
                except Exception as e:
                    print(f"[ERROR] Nie można załadować {filename}: {e}")

asyncio.run(main())


