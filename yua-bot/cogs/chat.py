import discord
from discord.ext import commands
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
from groq import Groq
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

        self.user_memory = {}
        self.user_cooldowns = {}
        self.cooldown_warned = set()

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
        try:
            print("[Groq] Trying llama-3.3-70b-versatile...")
            client = Groq(api_key=self.groq_key)
            completion = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": user_prompt},
                ],
                max_tokens=512,
                temperature=0.9,
            )
            text = completion.choices[0].message.content
            if text and text.strip():
                print("[Groq] SUCCESS")
                return text.strip()
            else:
                print("[Groq] empty response.")
        except Exception as e:
            print(f"[Groq] ERROR — {e}")
        return ""

    # ------------------------------------------------------------------
    # Master generate — tries all three sources in order
    # ------------------------------------------------------------------
    def generate_response(self, full_prompt: str, system_prompt: str, user_prompt: str) -> str:
        # Step 1: Gemini Key 1
        result = self._try_gemini(self.key1, 1, full_prompt)
        if result:
            return result

        # Step 2: Gemini Key 2
        if self.key2:
            result = self._try_gemini(self.key2, 2, full_prompt)
            if result:
                return result

        # Step 3: Groq (Llama 3) fallback
        result = self._try_groq(system_prompt, user_prompt)
        if result:
            return result

        # Step 4: Everything failed
        print("All sources failed.")
        return ""

    # ------------------------------------------------------------------
    # Memory helpers
    # ------------------------------------------------------------------
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
                    self.store_message(user_id, "User", user_prompt)
                    self.store_message(user_id, "Yua", greeting)
                    return

                system_prompt = build_system_prompt(user_name)
                memory_context = self.get_memory_context(user_id)

                full_prompt = (
                    f"{system_prompt}\n"
                    f"Current mood emoji: {mood_emoji}\n"
                    f"{memory_context}"
                    f"\nUser: {user_prompt}\nYua:"
                )

                self.store_message(user_id, "User", user_prompt)

                reply_text = self.generate_response(full_prompt, system_prompt, user_prompt)

                if not reply_text:
                    reply_text = (
                        f"Amar brain asholei ekhon kaj korche na, {user_name}! "
                        f"Ektu por try koro. 🌸"
                    )

                self.store_message(user_id, "Yua", reply_text)
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
