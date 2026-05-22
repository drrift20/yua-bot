import os
import asyncio
import threading
import discord
from discord.ext import commands
from flask import Flask

# --- Flask keepalive server ---
app = Flask(__name__)

@app.route("/")
def home():
    return "I am alive", 200

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    try:
        app.run(host="0.0.0.0", port=port)
    except Exception as e:
        print(f"Flask could not start on port {port}: {e}")

# --- Discord bot ---
intents = discord.Intents.default()
intents.message_content = True
intents.messages = True
intents.guilds = True
intents.dm_messages = True

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    print(f"API Key Loaded: {bool(os.getenv('GEMINI_API_KEY'))}")
    print("Yua is online! ✨")

async def main():
    async with bot:
        await bot.load_extension("cogs.chat")
        token = os.environ.get("DISCORD_TOKEN")
        if not token:
            raise ValueError("DISCORD_TOKEN environment variable is not set.")
        await bot.start(token)

if __name__ == "__main__":
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    print(f"Flask keepalive running on port {os.environ.get('PORT', 8080)}")
    asyncio.run(main())
