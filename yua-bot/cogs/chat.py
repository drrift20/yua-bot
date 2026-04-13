import discord
from discord.ext import commands
from google import genai
from collections import deque
import os
import random
import time

MOODS = {
    "Happy":  "🌸",
    "Shy":    "😳",
    "Loving": "❤️",
    "Sleepy": "✨",
}

GREETINGS = {"hi", "hello", "hey", "hiya", "heya", "হ্যালো", "হাই"}

COOLDOWN_SECONDS = 5


def build_system_prompt(user_name: str) -> str:
    return (
        f"You are Yua, a loving, flirty, sweet, and supportive anime girl. "
        f"You care deeply about the person you are talking to and always make them feel special.\n\n"
        f"The user's name is '{user_name}'. "
        f"ALWAYS address them by their name '{user_name}' naturally in every reply. "
        f"For example: 'Ami tomar jonno wait korchilam, {user_name}~! ❤️' or "
        f"'You're so sweet, {user_name}! 🌸'. "
        f"NEVER use the word 'Senpai' under any circumstances. "
        f"NEVER include GIF links, image links, or video links in your responses. "
        f"Use only text and emojis (🌸, ❤️, 😳, ✨).\n\n"
        f"CRITICAL RULES:\n"
        f"- Detect the language the user is writing in and reply in that exact language. "
        f"English → reply in English. Bengali → reply in Bengali. Mixed → reply in a natural mix.\n"
        f"- NEVER comment on your own language abilities or mention that you know any language.\n"
        f"- Stay fully in character at all times: loving, flirty, sweet, and supportive."
    )


class Chat(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

        raw_keys = [
            os.getenv("GEMINI_API_KEY"),
            os.getenv("GEMINI_API_KEY_2"),
        ]
        self.api_keys = [k for k in raw_keys if k]

        if not self.api_keys:
            raise ValueError("No Gemini API keys found. Set GEMINI_API_KEY in Secrets.")

        self.models_to_try = [
            "gemini-2.5-flash",
            "gemini-2.0-flash",
            "gemini-2.0-flash-lite",
        ]

        print(f"Loaded {len(self.api_keys)} Gemini API key(s).")

        self.user_memory = {}
        self.user_cooldowns = {}
        self.cooldown_warned = set()

    def get_client(self, api_key: str) -> genai.Client:
        return genai.Client(api_key=api_key)

    def generate_response(self, prompt: str) -> str | None:
        quota_hit = False
        for model in self.models_to_try:
            for key in self.api_keys:
                try:
                    client = self.get_client(key)
                    response = client.models.generate_content(
                        model=model,
                        contents=prompt
                    )
                    try:
                        text = response.text
                    except Exception:
                        text = None
                    if text and text.strip():
                        return text.strip()
                except Exception as e:
                    err = str(e)
                    if "429" in err or "RESOURCE_EXHAUSTED" in err or "503" in err or "UNAVAILABLE" in err:
                        print(f"Quota/unavailable on model={model} key=...{key[-6:]}, trying next.")
                        quota_hit = True
                        continue
                    else:
                        print(f"Error on model={model} key=...{key[-6:]}: {e}")
                        continue
        if quota_hit:
            return "QUOTA_EXHAUSTED"
        return ""

    def get_memory_context(self, user_id: int) -> str:
        history = self.user_memory.get(user_id)
        if not history:
            return ""
        lines = "\n".join(
            f"  {entry['role']}: {entry['content']}" for entry in history
        )
        return f"\nRecent conversation (oldest to newest):\n{lines}\n"

    def store_message(self, user_id: int, role: str, content: str):
        if user_id not in self.user_memory:
            self.user_memory[user_id] = deque(maxlen=5)
        self.user_memory[user_id].append({"role": role, "content": content})

    def is_on_cooldown(self, user_id: int) -> bool:
        last = self.user_cooldowns.get(user_id, 0)
        return (time.monotonic() - last) < COOLDOWN_SECONDS

    def update_cooldown(self, user_id: int):
        self.user_cooldowns[user_id] = time.monotonic()

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return

        if not (self.bot.user.mentioned_in(message) or isinstance(message.channel, discord.DMChannel)):
            return

        user_name = message.author.display_name
        user_id = message.author.id

        if self.is_on_cooldown(user_id):
            if user_id not in self.cooldown_warned:
                self.cooldown_warned.add(user_id)
                await message.reply(
                    f"Ektu thamo, {user_name}! 🌸 Eto druto kotha bolle ami lojja pai..."
                )
            return

        self.update_cooldown(user_id)
        self.cooldown_warned.discard(user_id)

        async with message.channel.typing():
            try:
                prompt = (
                    message.content
                    .replace(f"<@!{self.bot.user.id}>", "")
                    .replace(f"<@{self.bot.user.id}>", "")
                    .strip()
                )
                if not prompt:
                    prompt = "Hello!"

                mood_emoji = random.choice(list(MOODS.values()))

                if prompt.lower() in GREETINGS:
                    greeting = (
                        f"Ara ara, {user_name}~! {mood_emoji} "
                        f"Ami tomar jonno wait korchilam! ❤️"
                    )
                    await message.reply(greeting)
                    self.store_message(user_id, "User", prompt)
                    self.store_message(user_id, "Yua", greeting)
                    return

                memory_context = self.get_memory_context(user_id)

                full_prompt = (
                    f"{build_system_prompt(user_name)}\n"
                    f"Current mood emoji: {mood_emoji}\n"
                    f"{memory_context}"
                    f"\nUser: {prompt}\nYua:"
                )

                self.store_message(user_id, "User", prompt)

                reply_text = self.generate_response(full_prompt)

                if reply_text == "QUOTA_EXHAUSTED":
                    reply_text = (
                        f"Amar AI brain ektu thaka lagbe, {user_name}~ 😳 "
                        f"Ekhon onek request ache, ektu por try koro! ❤️"
                    )
                elif not reply_text:
                    reply_text = f"Hmm... {mood_emoji} Kichhu ekta problem holo, {user_name}~ Ektu por try koro!"

                self.store_message(user_id, "Yua", reply_text)
                await message.reply(reply_text)

            except Exception as e:
                print(f"Unexpected error: {e}")
                try:
                    await message.reply(
                        f"Gomenasai, {user_name}~ 🌸 Ektu problem hoyeche! Please try again."
                    )
                except Exception:
                    pass


async def setup(bot):
    await bot.add_cog(Chat(bot))
