from secrets import POSTGRES
from discord.ext import commands
import asyncpg


class DatabaseCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.bot.db = None  # <- instancja poola

    @commands.Cog.listener()
    async def on_ready(self):
        print("[BOOT] DatabaseCog załadowany – łączę z PostgreSQL...")
        try:
            conn = await asyncpg.connect(**POSTGRES)
            print("[BOOT] Połączono z bazą!")
            await conn.close()
        except Exception as e:
            print(f"Błąd połączenia: {e}")
        self.bot.db = await asyncpg.create_pool(**POSTGRES)
        await self.create_tables()
        print("[DB] Tabele utworzone (jeśli nie istniały)")

    async def create_tables(self):

        async with self.bot.db.acquire() as conn:

            # Users table
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    username TEXT,
                    timezone TEXT
                );
            """
            )

            # Tods
            await conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS tods (
                    id SERIAL,
                    boss_name TEXT,
                    epic BOOLEAN,              
                    killed_by TEXT,
                    reported_by TEXT,
                    tod BIGINT,
                    dropped BOOLEAN,
                    window_start BIGINT,
                    window_end BIGINT,
                    valid_report BOOLEAN
                );
            """
            )
            #Zaken doors
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS doors (
                    door_time BIGINT PRIMARY KEY                  
                    
                );
            """
            )

            # Spots
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS spots (
                    spot_name TEXT PRIMARY KEY,
                    emoji TEXT,
                    is_permanent BOOLEAN
                );
            """
            )

            # CP list
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS cp_list (
                    cp_name TEXT UNIQUE,
                    priority INTEGER UNIQUE
                );
            """
            )

            # Dibs
            #await conn.execute("DROP TABLE dibs") ################ DO USUNIĘCIA ##################
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS dibs (
                    id SERIAL PRIMARY KEY,
                    spot_name TEXT,
                    emoji TEXT,
                    is_permanent BOOLEAN,
                    status TEXT DEFAULT 'free',
                    cp_name TEXT,                    
                    priority INTEGER DEFAULT 0,
                    message_id BIGINT DEFAULT 0,                
                    dibs_start BIGINT DEFAULT 0 ,
                    dibs_end BIGINT DEFAULT 0,
                    farm_end BIGINT DEFAULT 0,        
                    pause_duration BIGINT DEFAULT 0            
                );
            """
            )

            # Blacklist
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS blacklist (
                    id SERIAL PRIMARY KEY,
                    cp_name TEXT,
                    spot TEXT,
                    blacklist_start BIGINT,
                    blacklist_end BIGINT,
                    pause_duration BIGINT
                );
            """
            )


async def setup(bot):
    await bot.add_cog(DatabaseCog(bot))
