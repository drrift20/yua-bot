import discord
from discord.ext import commands
from google import genai
from google.genai import types
from groq import Groq
from pymongo import MongoClient, ASCENDING
from collections import deque
import asyncio
import traceback
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
MEMORY_LIMIT = 15

GEMINI_MODELS = [
    "gemini-2.0-flash",
    "gemini-1.5-flash",
]

SAFETY_SETTINGS = [
    types.SafetySetting(category="HARM_CATEGORY_HARASSMENT",        threshold="BLOCK_NONE"),
    types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH",       threshold="BLOCK_NONE"),
    types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="BLOCK_NONE"),
    types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="BLOCK_NONE"),
]


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


# ===========================================================================
# Blocking I/O functions — all run in a thread pool via asyncio.to_thread()
# so they NEVER block the Discord event loop.
# ===========================================================================

def _sync_fetch_history(mongo_col, local_memory: dict, user_id: int) -> list:
    """Synchronous: fetch last MEMORY_LIMIT messages. Called via asyncio.to_thread."""
    uid = str(user_id)
    if mongo_col is not None:
        try:
            doc = mongo_col.find_one({"user_id": uid})
            if doc:
                return doc.get("messages", [])
        except Exception:
            print(f"[MongoDB] fetch_history error for user {uid}:")
            traceback.print_exc()
    return list(local_memory.get(user_id, []))


def _sync_save_message(mongo_col, local_memory: dict, user_id: int, role: str, content: str):
    """Synchronous: persist one message. Called via asyncio.to_thread."""
    uid = str(user_id)
    entry = {"role": role, "content": content}

    if user_id not in local_memory:
        local_memory[user_id] = deque(maxlen=MEMORY_LIMIT)
    local_memory[user_id].append(entry)

    if mongo_col is not None:
        try:
            mongo_col.update_one(
                {"user_id": uid},
                {
                    "$push": {
                        "messages": {
                            "$each": [entry],
                            "$slice": -MEMORY_LIMIT,
                        }
                    }
                },
                upsert=True,
            )
        except Exception:
            print(f"[MongoDB] save_message error for user {uid}:")
            traceback.print_exc()


def _sync_try_gemini(api_key: str, key_num: int, prompt: str) -> str:
    """Synchronous: attempt Gemini generation. Called via asyncio.to_thread."""
    client = genai.Client(api_key=api_key)
    for model_name in GEMINI_MODELS:
        try:
            print(f"[Gemini Key {key_num}] Trying model: {model_name}")
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    safety_settings=SAFETY_SETTINGS,
                ),
            )
            try:
                text = response.text
            except Exception:
                print(f"[Gemini Key {key_num}] model={model_name}: response.text failed:")
                traceback.print_exc()
                text = None
            if text and text.strip():
                print(f"[Gemini Key {key_num}] model={model_name}: SUCCESS")
                return text.strip()
            else:
                print(f"[Gemini Key {key_num}] model={model_name}: empty response, trying next.")
        except Exception:
            err = str(traceback.format_exc())
            if "429" in err or "RESOURCE_EXHAUSTED" in err:
                print(f"[Gemini Key {key_num}] model={model_name}: QUOTA ERROR")
            elif "503" in err or "UNAVAILABLE" in err:
                print(f"[Gemini Key {key_num}] model={model_name}: SERVER UNAVAILABLE")
            elif "404" in err or "NOT_FOUND" in err:
                print(f"[Gemini Key {key_num}] model={model_name}: MODEL NOT FOUND")
            else:
                print(f"[Gemini Key {key_num}] model={model_name}: UNKNOWN ERROR")
            traceback.print_exc()
    return ""


def _sync_try_groq(groq_key: str, system_prompt: str, user_prompt: str) -> str:
    """Synchronous: attempt Groq generation. Called via asyncio.to_thread."""
    if not groq_key:
        print("[Groq] No GROQ_API_KEY set, skipping.")
        return ""
    groq_models = [
        "llama3-8b-8192",
        "mixtral-8x7b-32768",
        "llama-3.3-70b-versatile",
    ]
    client = Groq(api_key=groq_key)
    for groq_model in groq_models:
        try:
            print(f"[Groq] Trying {groq_model}...")
            completion = client.chat.completions.create(
                model=groq_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": user_prompt},
                ],
                max_tokens=512,
                temperature=0.9,
            )
            text = completion.choices[0].message.content
            if text and text.strip():
                print(f"[Groq] {groq_model}: SUCCESS")
                return text.strip()
            else:
                print(f"[Groq] {groq_model}: empty response, trying next.")
        except Exception:
            print(f"[Groq] {groq_model}: ERROR")
            traceback.print_exc()
    return ""


def _sync_generate_response(
    key1: str, key2: str, groq_key: str,
    full_prompt: str, system_prompt: str, user_prompt: str
) -> str:
    """Synchronous: full waterfall through all AI sources. Called via asyncio.to_thread."""
    result = _sync_try_gemini(key1, 1, full_prompt)
    if result:
        return result
    if key2:
        result = _sync_try_gemini(key2, 2, full_prompt)
        if result:
            return result
    result = _sync_try_groq(groq_key, system_prompt, user_prompt)
    if result:
        return result
    print("[generate] All sources failed.")
    return ""


# ===========================================================================
# Cog
# ===========================================================================

class Chat(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

        # --- Gemini Configuration 1 ---
        self.key1 = os.getenv("GEMINI_API_KEY")
        # --- Gemini Configuration 2 ---
        self.key2 = os.getenv("GEMINI_API_KEY_2")
        # --- Groq Fallback ---
        self.groq_key = os.getenv("GROQ_API_KEY")

        if not self.key1:
            raise ValueError("GEMINI_API_KEY is not set in Secrets.")

        gemini_count = sum(1 for k in [self.key1, self.key2] if k)
        groq_status = "yes" if self.groq_key else "not set"
        print(f"Loaded {gemini_count} Gemini key(s). Groq fallback: {groq_status}.")

        # --- MongoDB Permanent Memory ---
        self.mongo_col = None
        mongo_uri = os.getenv("MONGO_URI")
        if mongo_uri:
            try:
                client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
                client.admin.command("ping")
                db = client["yua_bot"]
                self.mongo_col = db["memory"]
                self.mongo_col.create_index([("user_id", ASCENDING)], unique=True)
                print("MongoDB connected. Permanent memory active.")
            except Exception:
                print("MongoDB connection failed, using in-memory fallback:")
                traceback.print_exc()
        else:
            print("MONGO_URI not set. Using in-memory memory only.")

        # In-memory fallback / session cache
        self.local_memory: dict = {}
        self.user_cooldowns: dict = {}
        self.cooldown_warned: set = set()

    # ------------------------------------------------------------------
    # Async wrappers — these await thread-pool execution so the event
    # loop is NEVER blocked by database or HTTP calls.
    # ------------------------------------------------------------------
    async def fetch_history(self, user_id: int) -> list:
        return await asyncio.to_thread(
            _sync_fetch_history, self.mongo_col, self.local_memory, user_id
        )

    async def save_message(self, user_id: int, role: str, content: str):
        await asyncio.to_thread(
            _sync_save_message, self.mongo_col, self.local_memory, user_id, role, content
        )

    async def generate_response(
        self, full_prompt: str, system_prompt: str, user_prompt: str
    ) -> str:
        return await asyncio.to_thread(
            _sync_generate_response,
            self.key1, self.key2, self.groq_key,
            full_prompt, system_prompt, user_prompt,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def build_memory_context(self, history: list) -> str:
        if not history:
            return ""
        lines = "\n".join(f"  {m['role']}: {m['content']}" for m in history)
        return f"\nConversation history (oldest to newest):\n{lines}\n"

    def is_on_cooldown(self, user_id: int) -> bool:
        return (time.monotonic() - self.user_cooldowns.get(user_id, 0)) < COOLDOWN_SECONDS

    def update_cooldown(self, user_id: int):
        self.user_cooldowns[user_id] = time.monotonic()

    # ------------------------------------------------------------------
    # on_message — fully non-blocking
    # ------------------------------------------------------------------
    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return

        if not (self.bot.user.mentioned_in(message) or isinstance(message.channel, discord.DMChannel)):
            return

        user_name = message.author.display_name
        user_id = message.author.id

        # Cooldown check
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
                user_prompt = (
                    message.content
                    .replace(f"<@!{self.bot.user.id}>", "")
                    .replace(f"<@{self.bot.user.id}>", "")
                    .strip()
                )
                if not user_prompt:
                    user_prompt = "Hello!"

                mood_emoji = random.choice(list(MOODS.values()))

                # Fast greeting path — still saves to memory asynchronously
                if user_prompt.lower() in GREETINGS:
                    greeting = (
                        f"Ara ara, {user_name}~! {mood_emoji} "
                        f"Ami tomar jonno wait korchilam! ❤️"
                    )
                    await message.reply(greeting)
                    await self.save_message(user_id, "User", user_prompt)
                    await self.save_message(user_id, "Yua", greeting)
                    return

                # Fetch permanent history (non-blocking)
                history = await self.fetch_history(user_id)
                memory_context = self.build_memory_context(history)
                system_prompt = build_system_prompt(user_name)

                full_prompt = (
                    f"{system_prompt}\n"
                    f"Current mood emoji: {mood_emoji}\n"
                    f"{memory_context}"
                    f"\nUser: {user_prompt}\nYua:"
                )

                # Save user message (non-blocking, fire before API call)
                await self.save_message(user_id, "User", user_prompt)

                # Generate response (non-blocking — runs in thread pool)
                reply_text = await self.generate_response(full_prompt, system_prompt, user_prompt)

                if not reply_text:
                    reply_text = (
                        f"Amar brain asholei ekhon kaj korche na, {user_name}! "
                        f"Ektu por try koro. 🌸"
                    )

                # Save Yua's reply (non-blocking)
                await self.save_message(user_id, "Yua", reply_text)
                await message.reply(reply_text)

            except Exception:
                print(f"[on_message] Unhandled exception for user={user_id} guild={getattr(message.guild, 'id', 'DM')}:")
                traceback.print_exc()
                try:
                    await message.reply(
                        f"Amar brain asholei ekhon kaj korche na, {user_name}! "
                        f"Ektu por try koro. 🌸"
                    )
                except Exception:
                    traceback.print_exc()


async def setup(bot):
    await bot.add_cog(Chat(bot))
