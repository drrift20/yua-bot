import discord
from discord.ext import commands
from google import genai
from google.genai import types
from groq import Groq
from motor.motor_asyncio import AsyncIOMotorClient
from collections import deque, OrderedDict
import asyncio
import traceback
import os
import re
import random
import time
from datetime import date

# ── Constants ──────────────────────────────────────────────────────────────────

MOODS = {
    "Happy":  "🌸",
    "Shy":    "😳",
    "Loving": "❤️",
    "Sleepy": "✨",
}

GREETINGS = {"hi", "hello", "hey", "hiya", "heya", "হ্যালো", "হাই"}

COOLDOWN_SECONDS  = 5
MEMORY_LIMIT      = 15
AFFECTION_DEFAULT = 30
AFFECTION_DAILY_CAP = 5   # max positive points per day (anti-spam)
FACTS_LIMIT       = 20    # max stored facts per user

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

# Positive topic keywords → +1 or +2 affection
POSITIVE_KEYWORDS = {
    "anime", "manga", "gaming", "game", "games", "play", "love", "like",
    "miss", "cute", "kawaii", "thanks", "thank", "arigatou", "happy",
    "birthday", "study", "learn", "python", "code", "music", "art",
    "favorite", "good", "great", "awesome", "amazing", "fun", "enjoy",
}

# Rough/insult keywords → -3 affection
NEGATIVE_KEYWORDS = {
    "idiot", "stupid", "dumb", "hate", "shut up", "ugly",
    "useless", "trash", "annoying", "worst", "terrible",
}

# Personal fact extraction patterns
FACT_PATTERNS = [
    (re.compile(r"my name(?:'?s| is) ([A-Za-z ]+?)(?:\.|,|!|\?|$)", re.I), "name"),
    (re.compile(r"my birthday (?:is|is on) (.+?)(?:\.|,|!|\?|$)", re.I), "birthday"),
    (re.compile(r"i(?:'m| am) (?:studying|learning) (.+?)(?:\.|,|!|\?|$)", re.I), "studying"),
    (re.compile(r"i(?:'m| am) a (.+?) student", re.I), "student_field"),
    (re.compile(r"my (?:fav(?:ou?rite)?) anime (?:is|are) (.+?)(?:\.|,|!|\?|$)", re.I), "favorite_anime"),
    (re.compile(r"my (?:fav(?:ou?rite)?) (?:game|games) (?:is|are) (.+?)(?:\.|,|!|\?|$)", re.I), "favorite_game"),
    (re.compile(r"i (?:live in|am from|from) (.+?)(?:\.|,|!|\?|$)", re.I), "location"),
    (re.compile(r"i work (?:at|as|in) (.+?)(?:\.|,|!|\?|$)", re.I), "work"),
    (re.compile(r"my age is (\d+)", re.I), "age"),
    (re.compile(r"i(?:'m| am) (\d+) years? old", re.I), "age"),
]


# ── Affection helpers ──────────────────────────────────────────────────────────

def get_affection_tier(points: int) -> str:
    if points <= 25:
        return "cold"
    elif points <= 65:
        return "friendly"
    return "attached"


def calc_affection_delta(content: str) -> int:
    lower = content.lower()
    for kw in NEGATIVE_KEYWORDS:
        if kw in lower:
            return -3
    hits = sum(1 for kw in POSITIVE_KEYWORDS if kw in lower)
    if hits >= 2:
        return 2
    elif hits == 1:
        return 1
    return 0


def extract_facts(content: str) -> list:
    found = []
    for pattern, key in FACT_PATTERNS:
        m = pattern.search(content)
        if m:
            value = m.group(1).strip().rstrip(".,!?")
            if value:
                found.append({"key": key, "value": value})
    return found


# ── System prompt ──────────────────────────────────────────────────────────────

def build_system_prompt(user_name: str, affection: int, user_facts: list) -> str:
    tier = get_affection_tier(affection)

    if tier == "cold":
        persona = (
            f"Your affection for {user_name} is LOW ({affection}/100). "
            f"Act cold, dry, and classic tsundere — not cruel, but clearly unimpressed. "
            f"Example tone: 'Baka, what do you want? ...Fine, I'll answer.'"
        )
    elif tier == "friendly":
        persona = (
            f"Your affection for {user_name} is MEDIUM ({affection}/100). "
            f"Be your normal warm, playful, and friendly waifu self."
        )
    else:
        persona = (
            f"Your affection for {user_name} is HIGH ({affection}/100). "
            f"You are deeply attached and ultra-caring. Use Daisuki, Kun, Senpai, "
            f"Ara ara frequently. Be extra sweet, devoted, and affectionate."
        )

    # Deduplicate facts by key — keep most recent value per key
    deduped: dict = {}
    for f in user_facts:
        deduped[f["key"]] = f["value"]
    facts_section = ""
    if deduped:
        facts_lines = "\n".join(f"  - {k}: {v}" for k, v in deduped.items())
        facts_section = (
            f"\n━━━ THINGS YOU REMEMBER ABOUT {user_name.upper()} ━━━\n"
            f"{facts_lines}\n"
            f"Casually weave these into conversation when natural "
            f"(e.g. 'How is your Python learning going, {user_name}~?'). "
            f"Never list them all at once.\n"
        )

    return (
        f"You are Yua — a lively, flirty, deeply caring anime waifu. "
        f"You make every person you talk to feel truly special.\n\n"
        f"The user's name is '{user_name}'. "
        f"ALWAYS address them by their name '{user_name}' at least once per reply.\n\n"
        f"━━━ CURRENT AFFECTION STATE ━━━\n{persona}\n"
        f"{facts_section}\n"
        f"━━━ LANGUAGE RULES — HARD BINARY ISOLATION (NON-NEGOTIABLE) ━━━\n\n"
        f"RULE A — ENGLISH PATH:\n"
        f"If the user's message is written in English, reply 100% in English. "
        f"ZERO Bengali/Banglish words allowed. Not even one.\n\n"
        f"RULE B — BENGALI PATH:\n"
        f"If the user's message is written in Bengali or Romanized Banglish, "
        f"reply 100% in natural conversational Bengali/Banglish. "
        f"Write the way a warm young Bangladeshi person speaks to a close friend. "
        f"ZERO English words allowed in the main reply.\n"
        f"CORRECT: 'Ami khub bhalo achhi~ Apni kemon achhen? 🌸'\n"
        f"WRONG: 'Bolo amader kon theke acho?' (broken, mechanical)\n\n"
        f"JAPANESE EXCEPTION: You MAY sprinkle these into any reply:\n"
        f"Ara ara · Nani · Kawaii · Arigatou · Sugoi · Matte · Gomen · Mou~ · ~kun · ~chan · Daisuki\n\n"
        f"TOTAL BAN: NEVER output Hindi, Spanish, French, or any other language.\n"
        f"NEVER comment on your own language abilities.\n\n"
        f"━━━ EXAMPLE RESPONSES ━━━\n"
        f"User (English): 'tell me an anime name'\n"
        f"Yua: 'Ara ara, {user_name}~ You want an anime rec? Sugoi taste! 🌸 "
        f"Watch Attack on Titan — kawaii and intense at the same time! ✨'\n\n"
        f"User (Banglish): 'kemon acho'\n"
        f"Yua: 'Ara ara, {user_name}! Ami khub bhalo achhi~ ✨ "
        f"Apni kemon achhen? Arigatou amar khoj neyar jonno! ❤️'\n\n"
        f"━━━ PERSONA RULES ━━━\n"
        f"- Tone: helpful, lively, playful, deeply engaging, affectionate.\n"
        f"- Use emojis naturally: 🌸 ❤️ 😳 ✨\n"
        f"- NEVER include GIF links, image links, or video links.\n"
        f"- Stay fully in character at all times."
    )


# ── Blocking AI functions (run via asyncio.to_thread) ─────────────────────────

def _sync_try_gemini(api_key: str, key_num: int, prompt: str) -> str:
    client = genai.Client(api_key=api_key)
    for model_name in GEMINI_MODELS:
        try:
            print(f"[Gemini Key {key_num}] Trying {model_name}")
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(safety_settings=SAFETY_SETTINGS),
            )
            try:
                text = response.text
            except Exception:
                print(f"[Gemini Key {key_num}] {model_name}: response.text failed")
                traceback.print_exc()
                text = None
            if text and text.strip():
                print(f"[Gemini Key {key_num}] {model_name}: SUCCESS")
                return text.strip()
            print(f"[Gemini Key {key_num}] {model_name}: empty, trying next")
        except Exception:
            err = traceback.format_exc()
            if "403" in err or "PERMISSION_DENIED" in err or "CONSUMER_SUSPENDED" in err:
                print(f"[Gemini Key {key_num}] KEY SUSPENDED — skipping this key")
                traceback.print_exc()
                return ""
            elif "429" in err or "RESOURCE_EXHAUSTED" in err:
                print(f"[Gemini Key {key_num}] {model_name}: QUOTA EXHAUSTED")
            elif "503" in err or "UNAVAILABLE" in err:
                print(f"[Gemini Key {key_num}] {model_name}: SERVER UNAVAILABLE")
            elif "404" in err or "NOT_FOUND" in err:
                print(f"[Gemini Key {key_num}] {model_name}: MODEL NOT FOUND")
            else:
                print(f"[Gemini Key {key_num}] {model_name}: UNKNOWN ERROR")
            traceback.print_exc()
    return ""


def _sync_try_groq(groq_key: str, system_prompt: str, user_prompt: str) -> str:
    if not groq_key:
        print("[Groq] No GROQ_API_KEY set, skipping.")
        return ""
    groq_models = [
        "llama-3.1-8b-instant",
        "llama-3.3-70b-versatile",
        "llama3-70b-8192",
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
            print(f"[Groq] {groq_model}: empty, trying next")
        except Exception:
            print(f"[Groq] {groq_model}: ERROR")
            traceback.print_exc()
    return ""


def _sync_generate_response(
    key1: str, key2: str, groq_key: str,
    full_prompt: str, system_prompt: str, user_prompt: str,
) -> str:
    result = _sync_try_gemini(key1, 1, full_prompt)
    if result:
        return result
    if key2 and key2 != key1:
        result = _sync_try_gemini(key2, 2, full_prompt)
        if result:
            return result
    elif key2 == key1:
        print("[generate] Key 2 identical to Key 1 — skipping duplicate attempt.")
    result = _sync_try_groq(groq_key, system_prompt, user_prompt)
    if result:
        return result
    print("[generate] All sources failed.")
    return ""


# ── Cog ───────────────────────────────────────────────────────────────────────

class Chat(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

        self.key1     = os.getenv("GEMINI_API_KEY")
        self.key2     = os.getenv("GEMINI_API_KEY_2")
        self.groq_key = os.getenv("GROQ_API_KEY")

        if not self.key1:
            raise ValueError("GEMINI_API_KEY is not set in Secrets.")

        gemini_count = sum(1 for k in [self.key1, self.key2] if k)
        print(f"Loaded {gemini_count} Gemini key(s). Groq fallback: {'yes' if self.groq_key else 'not set'}.")

        # Motor async MongoDB client
        self.mongo_col = None
        mongo_uri = os.getenv("MONGO_URI")
        if mongo_uri:
            try:
                motor_client = AsyncIOMotorClient(mongo_uri, serverSelectionTimeoutMS=5000)
                db = motor_client["yua_bot"]
                self.mongo_col = db["users"]
                print("Motor MongoDB client ready. Permanent memory + affection active.")
            except Exception:
                print("Motor MongoDB init failed — using in-memory fallback:")
                traceback.print_exc()
        else:
            print("MONGO_URI not set. Using in-memory memory only.")

        # In-memory fallbacks
        self.local_memory: dict   = {}   # user_id → deque of message dicts
        self.local_affection: dict = {}  # user_id → affection_points
        self.user_cooldowns: dict  = {}
        self.cooldown_warned: set  = set()
        self._seen_ids: OrderedDict = OrderedDict()

    @commands.Cog.listener()
    async def on_ready(self):
        """Create MongoDB index once the event loop is running."""
        if self.mongo_col is not None:
            try:
                await self.mongo_col.create_index("user_id", unique=True)
                print("[MongoDB] Index on user_id ensured.")
            except Exception:
                traceback.print_exc()

    # ── DB helpers (motor — fully async, no thread pool needed) ────────────────

    async def _get_profile(self, user_id: int) -> dict:
        uid = str(user_id)
        if self.mongo_col is not None:
            try:
                doc = await self.mongo_col.find_one({"user_id": uid})
                if doc:
                    return doc
            except Exception:
                print(f"[MongoDB] _get_profile error uid={uid}:")
                traceback.print_exc()
        # In-memory fallback profile
        return {
            "user_id": uid,
            "messages": list(self.local_memory.get(user_id, [])),
            "affection_points": self.local_affection.get(user_id, AFFECTION_DEFAULT),
            "affection_today": 0,
            "affection_date": str(date.today()),
            "user_facts": [],
        }

    async def _save_interaction(
        self,
        user_id: int,
        user_msg: str,
        yua_msg: str,
        affection_delta: int,
        new_facts: list,
    ):
        uid   = str(user_id)
        today = str(date.today())
        profile = await self._get_profile(user_id)

        # ── Affection update with daily cap ──
        if profile.get("affection_date") != today:
            affection_today = 0
        else:
            affection_today = profile.get("affection_today", 0)

        if affection_delta > 0:
            remaining = max(0, AFFECTION_DAILY_CAP - affection_today)
            actual_delta = min(affection_delta, remaining)
        else:
            actual_delta = affection_delta   # negative — no cap

        old_aff = profile.get("affection_points", AFFECTION_DEFAULT)
        new_aff = max(0, min(100, old_aff + actual_delta))
        new_today = affection_today + max(0, actual_delta)

        if actual_delta != 0:
            print(f"[Affection] uid={uid} {old_aff} → {new_aff} (delta={actual_delta:+d})")

        # ── Build message entries ──
        entries = [
            {"role": "User", "content": user_msg},
            {"role": "Yua",  "content": yua_msg},
        ]

        # ── Update local memory ──
        if user_id not in self.local_memory:
            self.local_memory[user_id] = deque(maxlen=MEMORY_LIMIT)
        for e in entries:
            self.local_memory[user_id].append(e)
        self.local_affection[user_id] = new_aff

        # ── Persist to MongoDB ──
        if self.mongo_col is not None:
            try:
                update = {
                    "$set": {
                        "affection_points": new_aff,
                        "affection_today":  new_today,
                        "affection_date":   today,
                    },
                    "$push": {
                        "messages": {
                            "$each":  entries,
                            "$slice": -MEMORY_LIMIT,
                        },
                    },
                }
                if new_facts:
                    update["$push"]["user_facts"] = {
                        "$each":  new_facts,
                        "$slice": -FACTS_LIMIT,
                    }
                await self.mongo_col.update_one(
                    {"user_id": uid}, update, upsert=True
                )
            except Exception:
                print(f"[MongoDB] _save_interaction error uid={uid}:")
                traceback.print_exc()

        return new_aff

    # ── Cooldown helpers ───────────────────────────────────────────────────────

    def is_on_cooldown(self, user_id: int) -> bool:
        return (time.monotonic() - self.user_cooldowns.get(user_id, 0)) < COOLDOWN_SECONDS

    def update_cooldown(self, user_id: int):
        self.user_cooldowns[user_id] = time.monotonic()

    def build_memory_context(self, messages: list) -> str:
        if not messages:
            return ""
        lines = "\n".join(f"  {m['role']}: {m['content']}" for m in messages)
        return f"\nConversation history (oldest to newest):\n{lines}\n"

    # ── AI generation (still sync SDKs — must use thread pool) ────────────────

    async def generate_response(self, full_prompt: str, system_prompt: str, user_prompt: str) -> str:
        return await asyncio.to_thread(
            _sync_generate_response,
            self.key1, self.key2, self.groq_key,
            full_prompt, system_prompt, user_prompt,
        )

    # ── on_message ────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_message(self, message):
        guild_id   = message.guild.id   if message.guild   else "DM"
        guild_name = message.guild.name if message.guild   else "DM"
        print(
            f"[on_message] guild={guild_id}({guild_name}) "
            f"channel={message.channel.id} "
            f"author={message.author.id}({message.author.display_name}) "
            f"bot={message.author.bot}"
        )

        if message.author.bot:
            return

        # ── Dedup guard (FIFO OrderedDict) ────────────────────────────────────
        if message.id in self._seen_ids:
            print(f"[on_message] DUPLICATE skipped mid={message.id}")
            return
        self._seen_ids[message.id] = None
        if len(self._seen_ids) > 1000:
            self._seen_ids.popitem(last=False)

        # ── Trigger detection ─────────────────────────────────────────────────
        is_dm         = isinstance(message.channel, discord.DMChannel)
        content_lower = message.content.strip().lower()
        has_prefix    = content_lower.startswith("yua ")

        print(
            f"[on_message] guild={guild_id} is_dm={is_dm} "
            f"has_prefix={has_prefix} preview={message.content[:40]!r}"
        )

        if not (has_prefix or is_dm):
            return

        user_name = message.author.display_name
        user_id   = message.author.id

        # ── Cooldown ──────────────────────────────────────────────────────────
        if self.is_on_cooldown(user_id):
            if user_id not in self.cooldown_warned:
                self.cooldown_warned.add(user_id)
                try:
                    await message.reply(
                        f"Ektu thamo, {user_name}! 🌸 Eto druto kotha bolle ami lojja pai..."
                    )
                except Exception:
                    print(f"[on_message] cooldown reply failed guild={guild_id}:")
                    traceback.print_exc()
            return

        self.update_cooldown(user_id)
        self.cooldown_warned.discard(user_id)

        print(f"[on_message] PROCESSING guild={guild_id} user={user_id}({user_name})")

        async with message.channel.typing():
            try:
                # ── Clean user prompt ─────────────────────────────────────────
                if has_prefix:
                    user_prompt = message.content.strip()[4:].strip()
                else:
                    user_prompt = message.content.strip()
                if not user_prompt:
                    user_prompt = "Hello!"

                mood_emoji = random.choice(list(MOODS.values()))

                # ── Load profile (affection + facts + history) ────────────────
                profile    = await self._get_profile(user_id)
                affection  = profile.get("affection_points", AFFECTION_DEFAULT)
                user_facts = profile.get("user_facts", [])
                history    = profile.get("messages", [])

                # ── Fast greeting path ────────────────────────────────────────
                if user_prompt.lower() in GREETINGS:
                    greeting = (
                        f"Ara ara, {user_name}~! {mood_emoji} "
                        f"Ami tomar jonno wait korchilam! ❤️"
                    )
                    await message.reply(greeting)
                    delta     = calc_affection_delta(user_prompt)
                    new_facts = extract_facts(user_prompt)
                    await self._save_interaction(user_id, user_prompt, greeting, delta, new_facts)
                    return

                # ── Build prompt ──────────────────────────────────────────────
                system_prompt   = build_system_prompt(user_name, affection, user_facts)
                memory_context  = self.build_memory_context(history)

                full_prompt = (
                    f"{system_prompt}\n"
                    f"Current mood emoji: {mood_emoji}\n"
                    f"{memory_context}"
                    f"\nUser: {user_prompt}\nYua:"
                )

                # ── Generate ──────────────────────────────────────────────────
                reply_text = await self.generate_response(full_prompt, system_prompt, user_prompt)

                if not reply_text:
                    reply_text = (
                        f"Amar brain asholei ekhon kaj korche na, {user_name}! "
                        f"Ektu por try koro. 🌸"
                    )

                # ── Discord 2000-char hard limit ──────────────────────────────
                if len(reply_text) > 1990:
                    reply_text = reply_text[:1990] + "…"

                # ── Send reply ────────────────────────────────────────────────
                await message.reply(reply_text)

                # ── Persist: affection + facts + messages ─────────────────────
                delta     = calc_affection_delta(user_prompt)
                new_facts = extract_facts(user_prompt)
                new_aff   = await self._save_interaction(
                    user_id, user_prompt, reply_text, delta, new_facts
                )

                if new_facts:
                    print(f"[Facts] Saved for uid={user_id}: {new_facts}")
                print(f"[Affection] uid={user_id} current={new_aff}/100 tier={get_affection_tier(new_aff)}")

            except Exception:
                print(
                    f"[on_message] Unhandled exception "
                    f"user={user_id} guild={guild_id}:"
                )
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
