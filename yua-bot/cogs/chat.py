import discord
from discord.ext import commands
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
from groq import Groq
from pymongo import MongoClient, ASCENDING
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
MEMORY_LIMIT = 15

GEMINI_MODELS = [
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
            except Exception as e:
                print(f"MongoDB connection failed, using in-memory fallback: {e}")
        else:
            print("MONGO_URI not set. Using in-memory memory only.")

        # In-memory fallback (also used as a session cache)
        self.local_memory = {}
        self.user_cooldowns = {}
        self.cooldown_warned = set()

    # ------------------------------------------------------------------
    # MongoDB memory helpers
    # ------------------------------------------------------------------
    def fetch_history(self, user_id: int) -> list:
        """Fetch last MEMORY_LIMIT messages from MongoDB, or local cache."""
        uid = str(user_id)
        if self.mongo_col is not None:
            try:
                doc = self.mongo_col.find_one({"user_id": uid})
                if doc:
                    return doc.get("messages", [])
            except Exception as e:
                print(f"[MongoDB] fetch_history error: {e}")
        # Fallback to local
        return list(self.local_memory.get(user_id, []))

    def save_message(self, user_id: int, role: str, content: str):
        """Append a message and keep only the last MEMORY_LIMIT entries."""
        uid = str(user_id)
        entry = {"role": role, "content": content}

        # Always update local cache too
        if user_id not in self.local_memory:
            self.local_memory[user_id] = deque(maxlen=MEMORY_LIMIT)
        self.local_memory[user_id].append(entry)

        if self.mongo_col is not None:
            try:
                self.mongo_col.update_one(
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
            except Exception as e:
                print(f"[MongoDB] save_message error: {e}")

    def build_memory_context(self, history: list) -> str:
        """Format message history into a prompt context string."""
        if not history:
            return ""
        lines = "\n".join(f"  {m['role']}: {m['content']}" for m in history)
        return f"\nConversation history (oldest to newest):\n{lines}\n"

    # ------------------------------------------------------------------
    # Step 1 & 2 — Try Gemini Key 1, then Gemini Key 2
    # ------------------------------------------------------------------
    def _try_gemini(self, api_key: str, key_num: int, prompt: str) -> str:
        for model_name in GEMINI_MODELS:
            try:
                print(f"[Gemini Key {key_num}] Trying model: {model_name}")
                genai.configure(api_key=api_key)
                model = genai.GenerativeModel(
                    model_name=model_name,
                    safety_settings=SAFETY_SETTINGS,
                )
                response = model.generate_content(prompt)
                try:
                    text = response.text
                except Exception as inner:
                    print(f"[Gemini Key {key_num}] model={model_name}: response.text error: {inner}")
                    text = None
                if text and text.strip():
                    print(f"[Gemini Key {key_num}] model={model_name}: SUCCESS")
                    return text.strip()
                else:
                    print(f"[Gemini Key {key_num}] model={model_name}: empty response, trying next.")
            except Exception as e:
                err = str(e)
                if "429" in err or "RESOURCE_EXHAUSTED" in err:
                    print(f"[Gemini Key {key_num}] model={model_name}: QUOTA ERROR — {e}")
                elif "503" in err or "UNAVAILABLE" in err:
                    print(f"[Gemini Key {key_num}] model={model_name}: SERVER UNAVAILABLE — {e}")
                elif "404" in err or "NOT_FOUND" in err:
                    print(f"[Gemini Key {key_num}] model={model_name}: MODEL NOT FOUND — {e}")
                else:
                    print(f"[Gemini Key {key_num}] model={model_name}: UNKNOWN ERROR — {e}")
        return ""

    # ------------------------------------------------------------------
    # Step 3 — Groq fallback (Llama 3)
    # ------------------------------------------------------------------
    def _try_groq(self, system_prompt: str, user_prompt: str) -> str:
        if not self.groq_key:
            print("[Groq] No GROQ_API_KEY set, skipping.")
            return ""
        groq_models = [
            "llama3-8b-8192",
            "mixtral-8x7b-32768",
            "llama-3.3-70b-versatile",
        ]
        client = Groq(api_key=self.groq_key)
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
            except Exception as e:
                print(f"[Groq] {groq_model}: ERROR — {e}")
        return ""

    # ------------------------------------------------------------------
    # Master generate — tries all three sources in order
    # ------------------------------------------------------------------
    def generate_response(self, full_prompt: str, system_prompt: str, user_prompt: str) -> str:
        result = self._try_gemini(self.key1, 1, full_prompt)
        if result:
            return result
        if self.key2:
            result = self._try_gemini(self.key2, 2, full_prompt)
            if result:
                return result
        result = self._try_groq(system_prompt, user_prompt)
        if result:
            return result
        print("All sources failed.")
        return ""

    # ------------------------------------------------------------------
    # Cooldown helpers
    # ------------------------------------------------------------------
    def is_on_cooldown(self, user_id: int) -> bool:
        return (time.monotonic() - self.user_cooldowns.get(user_id, 0)) < COOLDOWN_SECONDS

    def update_cooldown(self, user_id: int):
        self.user_cooldowns[user_id] = time.monotonic()

    # ------------------------------------------------------------------
    # on_message
    # ------------------------------------------------------------------
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
                user_prompt = (
                    message.content
                    .replace(f"<@!{self.bot.user.id}>", "")
                    .replace(f"<@{self.bot.user.id}>", "")
                    .strip()
                )
                if not user_prompt:
                    user_prompt = "Hello!"

                mood_emoji = random.choice(list(MOODS.values()))

                if user_prompt.lower() in GREETINGS:
                    greeting = (
                        f"Ara ara, {user_name}~! {mood_emoji} "
                        f"Ami tomar jonno wait korchilam! ❤️"
                    )
                    await message.reply(greeting)
                    self.save_message(user_id, "User", user_prompt)
                    self.save_message(user_id, "Yua", greeting)
                    return

                # Fetch permanent history from MongoDB (or local cache)
                history = self.fetch_history(user_id)
                memory_context = self.build_memory_context(history)
                system_prompt = build_system_prompt(user_name)

                full_prompt = (
                    f"{system_prompt}\n"
                    f"Current mood emoji: {mood_emoji}\n"
                    f"{memory_context}"
                    f"\nUser: {user_prompt}\nYua:"
                )

                # Save the user's message before generating reply
                self.save_message(user_id, "User", user_prompt)

                reply_text = self.generate_response(full_prompt, system_prompt, user_prompt)

                if not reply_text:
                    reply_text = (
                        f"Amar brain asholei ekhon kaj korche na, {user_name}! "
                        f"Ektu por try koro. 🌸"
                    )

                # Save Yua's reply to memory
                self.save_message(user_id, "Yua", reply_text)
                await message.reply(reply_text)

            except Exception as e:
                print(f"Unexpected on_message error: {e}")
                try:
                    await message.reply(
                        f"Amar brain asholei ekhon kaj korche na, {user_name}! "
                        f"Ektu por try koro. 🌸"
                    )
                except Exception:
                    pass


async def setup(bot):
    await bot.add_cog(Chat(bot))
