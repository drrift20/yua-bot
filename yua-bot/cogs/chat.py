import discord
from discord.ext import commands
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
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

MODELS_TO_TRY = [
    "gemini-2.0-flash",
    "gemini-1.5-flash",
]

SAFETY_SETTINGS = {
    HarmCategory.HARM_CATEGORY_HARASSMENT:        HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HATE_SPEECH:       HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
}


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

        self.key1 = os.getenv("GEMINI_API_KEY")
        self.key2 = os.getenv("GEMINI_API_KEY_2")

        if not self.key1:
            raise ValueError("GEMINI_API_KEY is not set in Secrets.")

        key_count = sum(1 for k in [self.key1, self.key2] if k)
        print(f"Loaded {key_count} Gemini API key(s).")

        self.user_memory = {}
        self.user_cooldowns = {}
        self.cooldown_warned = set()

    def generate_response(self, prompt: str, user_name: str) -> str:
        keys = [k for k in [self.key1, self.key2] if k]

        for key_num, api_key in enumerate(keys, start=1):
            for model_name in MODELS_TO_TRY:
                try:
                    print(f"[Key {key_num}] Configuring with model: {model_name}")
                    genai.configure(api_key=api_key)
                    model = genai.GenerativeModel(
                        model_name=model_name,
                        safety_settings=SAFETY_SETTINGS,
                    )
                    response = model.generate_content(prompt)

                    try:
                        text = response.text
                    except Exception as inner:
                        print(f"[Key {key_num}] model={model_name}: response.text error: {inner}")
                        text = None

                    if text and text.strip():
                        print(f"[Key {key_num}] model={model_name}: SUCCESS")
                        return text.strip()
                    else:
                        print(f"[Key {key_num}] model={model_name}: empty response, trying next.")

                except Exception as e:
                    err = str(e)
                    if "429" in err or "RESOURCE_EXHAUSTED" in err:
                        print(f"[Key {key_num}] model={model_name}: QUOTA ERROR — {e}")
                    elif "503" in err or "UNAVAILABLE" in err:
                        print(f"[Key {key_num}] model={model_name}: SERVER UNAVAILABLE — {e}")
                    elif "404" in err or "NOT_FOUND" in err:
                        print(f"[Key {key_num}] model={model_name}: MODEL NOT FOUND — {e}")
                    else:
                        print(f"[Key {key_num}] model={model_name}: UNKNOWN ERROR — {e}")

        print("All keys and models failed.")
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

                reply_text = self.generate_response(full_prompt, user_name)

                if not reply_text:
                    reply_text = (
                        f"Gomenasai, {user_name}! 🌸 "
                        f"Amar brain ekhon ektu tired, ektu por abar kotha boli?"
                    )

                self.store_message(user_id, "Yua", reply_text)
                await message.reply(reply_text)

            except Exception as e:
                print(f"Unexpected on_message error: {e}")
                try:
                    await message.reply(
                        f"Gomenasai, {user_name}! 🌸 "
                        f"Amar brain ekhon ektu tired, ektu por abar kotha boli?"
                    )
                except Exception:
                    pass


async def setup(bot):
    await bot.add_cog(Chat(bot))
