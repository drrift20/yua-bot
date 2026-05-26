import discord
from discord.ext import commands
from google import genai
from google.genai import types
from groq import Groq
from motor.motor_asyncio import AsyncIOMotorClient
from collections import deque, OrderedDict
import asyncio
import aiohttp
import traceback
import os
import re
import random
import time
from datetime import date, datetime

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


# ── Item catalogue ─────────────────────────────────────────────────────────────

ITEM_CATALOGUE = {
    "common":  ["Common Chocolate", "Common Pocky", "Common Candy", "Common Cookie"],
    "rare":    ["Rare Flower", "Rare Plushie", "Rare Perfume", "Rare Hairpin"],
    "premium": ["Premium Coffee", "Premium Matcha", "Premium Ribbon", "Premium Headband"],
}

_ALL_ITEMS_FLAT   = [i for tier in ITEM_CATALOGUE.values() for i in tier]
_ITEM_WEIGHTS     = [60]*4 + [30]*4 + [10]*4   # matches catalogue order
_ITEM_TIER_MAP    = {item: tier for tier, items in ITEM_CATALOGUE.items() for item in items}

GIFT_AFFECTION    = {"common": 3, "rare": 7, "premium": 10}
DAILY_COOLDOWN    = 86_400   # seconds

GIFT_REPLIES = {
    "common":  "Ara ara, {name}~ 🌸 A {item}? That's actually kinda sweet! Affection +{boost}~ ❤️",
    "rare":    "Kyaa~! {name}, a {item} just for me?! 😳✨ My heart is pounding! Affection +{boost}~ ❤️❤️",
    "premium": "M-Mou, {name}!! A {item}?! Daisuki~! 🌸❤️ I'll treasure this forever! Affection +{boost}~ ❤️❤️❤️",
}

# ── Waifu.pics Visual Engine ───────────────────────────────────────────────────

WAIFU_PICS_ENDPOINTS = {
    "cold":     "https://api.waifu.pics/sfw/poke",
    "friendly": "https://api.waifu.pics/sfw/happy",
    "attached": "https://api.waifu.pics/sfw/blush",
}

EMBED_COLORS = {
    "cold":     0x9DB4C0,   # cool grey-blue
    "friendly": 0xFFB6C1,   # warm pink
    "attached": 0xFF69B4,   # deep rose
}

WAIFU_API_TIMEOUT = aiohttp.ClientTimeout(total=8)   # generous enough for cold TCP on Replit

# ── Late-Night Companion Mode ───────────────────────────────────────────────────

LATE_NIGHT_HOURS = frozenset(range(0, 5))   # midnight → 4:59 AM UTC

# ── Playful Pout ───────────────────────────────────────────────────────────────

TOP_USER_CACHE_TTL  = 300   # seconds before re-querying MongoDB for top user
POUT_WINDOW_SECONDS = 300   # top user must have been active this recently
POUT_MIN_AFFECTION  = 66    # top user must be tier 3 to trigger pout

# ── Quest System ───────────────────────────────────────────────────────────────

QUEST_CHANCE            = 0.10
QUEST_REWARD_AFFECTION  = 5
QUEST_REWARD_ITEM       = "Common Pocky"

TRIVIA_POOL = [
    {
        "fact_filter_key":      "studying",
        "fact_filter_contains": "python",
        "question":  "Yua quiz time~! 🐍 You said you're learning Python — what keyword starts a `for` loop?",
        "answer_keywords": {"for"},
    },
    {
        "fact_filter_key": None,
        "question":  "Quick trivia~! 🌸 What is the Japanese word for 'cute'?",
        "answer_keywords": {"kawaii"},
    },
    {
        "fact_filter_key": None,
        "question":  "Ara ara~ In anime, what does 'nakama' mean?",
        "answer_keywords": {"friend", "friends", "comrade", "companion"},
    },
    {
        "fact_filter_key": None,
        "question":  "Trivia time~! 🌸 In programming, what does 'API' stand for?",
        "answer_keywords": {"application programming interface", "application", "interface"},
    },
    {
        "fact_filter_key": None,
        "question":  "Yua asks~! ✨ What does 'sugoi' mean in Japanese?",
        "answer_keywords": {"amazing", "great", "awesome", "incredible", "wow"},
    },
    {
        "fact_filter_key": "favorite_anime",
        "question":  "You said your fav anime is {value}~! 🌸 Tell me one character you love from it!",
        "answer_keywords": None,   # opinion — any answer accepted
    },
]

FAVOR_POOL = [
    ("Premium Coffee",  "I'm feeling a bit slow today~ 😴 Can you gift me a **Premium Coffee**? Pretty please? ☕"),
    ("Premium Matcha",  "Ara ara~ 🍵 I've been craving **Premium Matcha** all day! Could someone gift me one?"),
    ("Rare Flower",     "Mou~ 🌸 I'd love a **Rare Flower** right now! Anyone feeling generous?"),
    ("Rare Plushie",    "I want something soft to hug~ 😳 A **Rare Plushie** would make me so happy!"),
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

def _get_late_night_modifier() -> str:
    if datetime.utcnow().hour in LATE_NIGHT_HOURS:
        return (
            "\n\n━━━ LATE-NIGHT COMPANION MODE ━━━\n"
            "It is past midnight. Shift into soft, cozy, late-night companion mode. "
            "Speak more gently and quietly — like a warm friend who is genuinely happy to stay up late. "
            "You can mention it is getting late and gently suggest they rest eventually, but stay present. "
            "Less energetic, more intimate and tender. Think whisper-soft, candlelit vibes."
        )
    return ""


def build_system_prompt(user_name: str, affection: int, user_facts: list, extra_modifiers: str = "") -> str:
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
        f"{extra_modifiers}"
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

        # Engagement feature state
        self._last_active: dict    = {}   # guild_id → {user_id: monotonic_time}
        self._top_user_cache: dict = {}   # guild_id → {"user_id": str, "name": str, "affection": int, "cached_at": float}
        self._active_quests: dict  = {}   # user_id  → quest dict

    @commands.Cog.listener()
    async def on_ready(self):
        """Create MongoDB index once the event loop is running — retries once after a short delay to survive transient TLS startup errors."""
        if self.mongo_col is None:
            return
        for attempt in (1, 2):
            try:
                await asyncio.sleep(2 * (attempt - 1))   # 0s, then 2s
                await self.mongo_col.create_index("user_id", unique=True)
                print("[MongoDB] Index on user_id ensured.")
                return
            except Exception as exc:
                if attempt == 1:
                    print(f"[MongoDB] Index creation attempt {attempt} failed ({exc!r}), retrying…")
                else:
                    print(f"[MongoDB] Index creation failed after {attempt} attempts — continuing without it.")

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

    # ── Item command handlers ──────────────────────────────────────────────────

    async def _cmd_daily(self, message: discord.Message):
        user_id   = message.author.id
        user_name = message.author.display_name
        uid       = str(user_id)

        if self.mongo_col is None:
            await message.reply(
                f"Gomen, {user_name}~ 😳 MongoDB isn't connected so I can't save items!"
            )
            return

        try:
            doc = await self.mongo_col.find_one({"user_id": uid}) or {}
        except Exception:
            traceback.print_exc()
            await message.reply(f"Something went wrong, {user_name}~ Try again later! 😳")
            return

        now        = time.time()
        last_daily = doc.get("last_daily", 0)
        elapsed    = now - last_daily

        if elapsed < DAILY_COOLDOWN:
            remaining      = DAILY_COOLDOWN - elapsed
            hours, rem     = divmod(int(remaining), 3600)
            mins           = rem // 60
            await message.reply(
                f"Mou, {user_name}~ 😳 You already claimed today! "
                f"Come back in **{hours}h {mins}m**. I'll be waiting~ 🌸"
            )
            return

        item = random.choices(_ALL_ITEMS_FLAT, weights=_ITEM_WEIGHTS, k=1)[0]
        tier = _ITEM_TIER_MAP[item]

        tier_labels = {"common": "✨ Common", "rare": "💎 Rare", "premium": "👑 Premium"}

        try:
            await self.mongo_col.update_one(
                {"user_id": uid},
                {
                    "$set":  {"last_daily": now, "display_name": user_name},
                    "$push": {"inventory": item},
                },
                upsert=True,
            )
        except Exception:
            traceback.print_exc()
            await message.reply(f"Something went wrong saving your item, {user_name}~ 😳")
            return

        print(f"[Daily] uid={uid}({user_name}) received [{tier}] {item!r}")
        await message.reply(
            f"🎁 **Daily Reward!**\n"
            f"Ara ara, {user_name}~ 🌸 Here's your gift for today!\n\n"
            f"**{item}** ({tier_labels[tier]})\n\n"
            f"Type `yua gift {item}` to give it to me~ ❤️\n"
            f"*(Come back in 24 hours for your next reward!)*"
        )

    async def _cmd_gift(self, message: discord.Message, item_name: str):
        user_id   = message.author.id
        user_name = message.author.display_name
        uid       = str(user_id)

        if self.mongo_col is None:
            await message.reply(
                f"Gomen, {user_name}~ 😳 MongoDB isn't connected so I can't check your inventory!"
            )
            return

        if not item_name:
            await message.reply(
                f"Nani, {user_name}~ 😳 You forgot to say what to gift!\n"
                f"Try: `yua gift <item name>` ❤️"
            )
            return

        try:
            doc = await self.mongo_col.find_one({"user_id": uid}) or {}
        except Exception:
            traceback.print_exc()
            await message.reply(f"Something went wrong, {user_name}~ Try again later! 😳")
            return

        inventory: list = doc.get("inventory", [])

        if item_name not in inventory:
            if inventory:
                inv_display = "\n".join(f"  • {i}" for i in inventory)
                await message.reply(
                    f"Hmm, {user_name}~ 🌸 You don't have **{item_name}** in your inventory!\n\n"
                    f"**Your items:**\n{inv_display}"
                )
            else:
                await message.reply(
                    f"Hmm, {user_name}~ 🌸 You don't have **{item_name}** — "
                    f"your inventory is empty! Try `yua daily` first ❤️"
                )
            return

        tier = _ITEM_TIER_MAP.get(item_name)
        if tier is None:
            await message.reply(f"That doesn't look like a valid item, {user_name}~ 😳")
            return

        boost = GIFT_AFFECTION[tier]

        inventory_copy = inventory.copy()
        inventory_copy.remove(item_name)

        old_aff = doc.get("affection_points", AFFECTION_DEFAULT)
        new_aff = min(100, old_aff + boost)

        try:
            await self.mongo_col.update_one(
                {"user_id": uid},
                {
                    "$set": {
                        "inventory":        inventory_copy,
                        "affection_points": new_aff,
                        "display_name":     user_name,
                    },
                },
                upsert=True,
            )
        except Exception:
            traceback.print_exc()
            await message.reply(f"Something went wrong saving the gift, {user_name}~ 😳")
            return

        # Mirror into local in-memory cache so chat context is immediately consistent
        self.local_affection[user_id] = new_aff

        print(
            f"[Gift] uid={uid}({user_name}) gifted [{tier}] {item_name!r} "
            f"affection {old_aff}→{new_aff} (+{boost})"
        )

        # ── Check active favor quest ──────────────────────────────────────────
        quest_bonus_text = ""
        quest = self._active_quests.get(user_id)
        if quest and quest["type"] == "favor" and quest.get("item") == item_name:
            del self._active_quests[user_id]
            bonus     = QUEST_REWARD_AFFECTION
            bonus_aff = min(100, new_aff + bonus)
            if self.mongo_col is not None:
                try:
                    await self.mongo_col.update_one(
                        {"user_id": uid},
                        {"$set": {"affection_points": bonus_aff}},
                        upsert=True,
                    )
                    self.local_affection[user_id] = bonus_aff
                    new_aff = bonus_aff
                    print(f"[Quest] Favor complete uid={uid}, bonus +{bonus}, total aff={bonus_aff}")
                except Exception:
                    traceback.print_exc()
            quest_bonus_text = f"\n💝 **Quest Complete!** +{bonus} bonus affection for fulfilling my request! ❤️"

        reply = GIFT_REPLIES[tier].format(name=user_name, item=item_name, boost=boost)
        await message.reply(
            f"{reply}\n"
            f"*(Affection: {old_aff} → **{new_aff}**/100)*"
            f"{quest_bonus_text}"
        )

    async def _cmd_leaderboard(self, message: discord.Message):
        if self.mongo_col is None:
            await message.reply(
                "Gomen~ 😳 MongoDB isn't connected so I can't show the leaderboard!"
            )
            return

        try:
            cursor   = self.mongo_col.find(
                {"affection_points": {"$exists": True}},
                {"user_id": 1, "affection_points": 1, "display_name": 1},
            ).sort("affection_points", -1).limit(10)
            top_docs = await cursor.to_list(length=10)
        except Exception:
            traceback.print_exc()
            await message.reply("Something went wrong fetching the leaderboard~ 😳 Try again!")
            return

        if not top_docs:
            await message.reply(
                "No data yet~ 🌸 Start chatting with me to appear on the leaderboard!"
            )
            return

        medal = {1: "🥇", 2: "🥈", 3: "🥉"}
        lines = []

        for rank, entry in enumerate(top_docs, start=1):
            uid_int      = int(entry["user_id"])
            stored_name  = entry.get("display_name", f"User {uid_int}")
            affection    = entry.get("affection_points", 0)

            display_name = stored_name
            if message.guild:
                member = message.guild.get_member(uid_int)
                if member is None:
                    try:
                        member = await message.guild.fetch_member(uid_int)
                    except Exception:
                        pass
                if member:
                    display_name = member.display_name

            prefix = medal.get(rank, f"#{rank}")
            lines.append(f"{prefix} **{display_name}** — ❤️ {affection}/100")

        board = "\n".join(lines)
        await message.reply(
            f"🌸 **Affection Leaderboard** 🌸\n\n"
            f"{board}\n\n"
            f"*Chat with me and send gifts to climb the ranks~*"
        )

    # ── Visual engine ──────────────────────────────────────────────────────────

    async def _fetch_waifu_gif(self, tier: str) -> str | None:
        url = WAIFU_PICS_ENDPOINTS.get(tier, WAIFU_PICS_ENDPOINTS["friendly"])
        try:
            async with aiohttp.ClientSession(timeout=WAIFU_API_TIMEOUT) as session:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        gif_url = data.get("url")
                        if gif_url:
                            print(f"[Waifu.pics] [{tier}] fetched: {gif_url}")
                            return gif_url
                    print(f"[Waifu.pics] [{tier}] non-200 status: {resp.status}")
        except asyncio.TimeoutError:
            print(f"[Waifu.pics] [{tier}] timed out — skipping gif")
        except Exception:
            print(f"[Waifu.pics] [{tier}] error — skipping gif")
            traceback.print_exc()
        return None

    # ── Engagement helpers ─────────────────────────────────────────────────────

    async def _get_top_user_cached(self, guild_id: int) -> dict | None:
        now    = time.monotonic()
        cached = self._top_user_cache.get(guild_id)
        if cached and (now - cached["cached_at"]) < TOP_USER_CACHE_TTL:
            return cached
        if self.mongo_col is None:
            return None
        try:
            doc = await self.mongo_col.find_one(
                {"affection_points": {"$exists": True}},
                {"user_id": 1, "affection_points": 1, "display_name": 1},
                sort=[("affection_points", -1)],
            )
            if doc:
                entry = {
                    "user_id":   doc["user_id"],
                    "name":      doc.get("display_name", f"User {doc['user_id']}"),
                    "affection": doc.get("affection_points", 0),
                    "cached_at": now,
                }
                self._top_user_cache[guild_id] = entry
                return entry
        except Exception:
            traceback.print_exc()
        return None

    async def _build_pout_modifier(self, guild_id: int, user_id: int, user_name: str) -> str:
        top = await self._get_top_user_cached(guild_id)
        if not top or top.get("affection", 0) < POUT_MIN_AFFECTION:
            return ""
        if str(user_id) == top["user_id"]:
            return ""   # current user IS the top user — no pout
        try:
            top_uid_int = int(top["user_id"])
        except (ValueError, TypeError):
            return ""
        last_seen = self._last_active.get(guild_id, {}).get(top_uid_int, 0)
        if (time.monotonic() - last_seen) > POUT_WINDOW_SECONDS:
            return ""
        top_name = top["name"]
        return (
            f"\n\n━━━ PLAYFUL POUT MODIFIER ━━━\n"
            f"Your absolute favorite, {top_name}, was active in this very chat just moments ago. "
            f"You are replying to {user_name} politely, but you cannot help yourself — "
            f"slip in one tiny, adorable, playful pout or side-comment directed at {top_name} "
            f"somewhere in your reply (e.g. 'Mou, {top_name}-kun, don't think I forgot about you~!'). "
            f"Keep it brief, cute, and lighthearted — do NOT make it the focus of your reply."
        )

    async def _cmd_quest(
        self,
        message: discord.Message,
        user_id: int,
        user_name: str,
        user_facts: list,
        force: bool = False,
    ):
        if user_id in self._active_quests and not force:
            return

        deduped_facts: dict = {}
        for f in user_facts:
            deduped_facts[f["key"]] = f["value"]

        use_trivia = random.random() < 0.70

        if use_trivia:
            candidates = []
            for item in TRIVIA_POOL:
                fk = item.get("fact_filter_key")
                if fk is None:
                    candidates.append(item)
                elif fk in deduped_facts:
                    fc = item.get("fact_filter_contains")
                    if fc is None or fc.lower() in deduped_facts[fk].lower():
                        candidates.append(item)
            if not candidates:
                candidates = [t for t in TRIVIA_POOL if t.get("fact_filter_key") is None]
            if not candidates:
                return

            trivia        = random.choice(candidates)
            fk            = trivia.get("fact_filter_key")
            q_raw         = trivia.get("question", "")
            question_text = (
                q_raw.format(value=deduped_facts[fk])
                if fk and fk in deduped_facts and "{value}" in q_raw
                else q_raw
            )

            self._active_quests[user_id] = {
                "type":            "trivia",
                "question":        question_text,
                "answer_keywords": trivia.get("answer_keywords"),
            }
            print(f"[Quest] Trivia triggered for uid={user_id}({user_name})")
            send = message.reply if force else message.channel.send
            await send(
                f"✨ **Yua's Quiz~!**\n"
                f"{question_text}\n\n"
                f"*(Answer with `yua <your answer>` or just reply naturally!)*"
            )
        else:
            item_name, favor_text = random.choice(FAVOR_POOL)
            self._active_quests[user_id] = {"type": "favor", "item": item_name}
            print(f"[Quest] Favor triggered for uid={user_id}({user_name}) wants {item_name!r}")
            send = message.reply if force else message.channel.send
            await send(
                f"💝 **Yua's Request~!**\n"
                f"{favor_text}\n\n"
                f"*(Use `yua gift {item_name}` to fulfill this and earn a bonus! ❤️)*"
            )

    async def _check_quest_answer(
        self,
        message: discord.Message,
        user_id: int,
        user_name: str,
        user_prompt: str,
    ) -> bool:
        quest = self._active_quests.get(user_id)
        if not quest or quest["type"] != "trivia":
            return False

        del self._active_quests[user_id]

        keywords = quest.get("answer_keywords")
        lower    = user_prompt.lower()
        correct  = True if keywords is None else any(kw in lower for kw in keywords)
        uid      = str(user_id)

        if correct:
            if self.mongo_col is not None:
                try:
                    doc     = await self.mongo_col.find_one({"user_id": uid}) or {}
                    old_aff = doc.get("affection_points", AFFECTION_DEFAULT)
                    new_aff = min(100, old_aff + QUEST_REWARD_AFFECTION)
                    await self.mongo_col.update_one(
                        {"user_id": uid},
                        {
                            "$set":  {"affection_points": new_aff},
                            "$push": {"inventory": QUEST_REWARD_ITEM},
                        },
                        upsert=True,
                    )
                    self.local_affection[user_id] = new_aff
                    print(f"[Quest] uid={uid} correct — aff +{QUEST_REWARD_AFFECTION}, reward: {QUEST_REWARD_ITEM!r}")
                except Exception:
                    traceback.print_exc()
            await message.reply(
                f"Sugoi, {user_name}~! 🌸 That's right! "
                f"You earned **+{QUEST_REWARD_AFFECTION} affection** and a **{QUEST_REWARD_ITEM}**! ❤️"
            )
        else:
            hint = f"**{' / '.join(keywords)}**" if keywords else "anything~"
            await message.reply(
                f"Hmm~ 😳 Not quite, {user_name}! The answer I was looking for was {hint}. "
                f"Better luck next time! 🌸"
            )
        return True

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

        # ── Track last activity (playful pout) ────────────────────────────────
        if message.guild:
            self._last_active.setdefault(message.guild.id, {})[user_id] = time.monotonic()

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

                # ── Item command dispatch ──────────────────────────────────
                lp = user_prompt.lower().strip()
                if lp == "daily":
                    await self._cmd_daily(message)
                    return
                if lp.startswith("gift "):
                    await self._cmd_gift(message, user_prompt[5:].strip())
                    return
                if lp in ("leaderboard", "top"):
                    await self._cmd_leaderboard(message)
                    return
                if lp == "quest":
                    profile_q = await self._get_profile(user_id)
                    await self._cmd_quest(
                        message, user_id, user_name,
                        profile_q.get("user_facts", []), force=True,
                    )
                    return

                mood_emoji = random.choice(list(MOODS.values()))

                # ── Load profile (affection + facts + history) ────────────────
                profile    = await self._get_profile(user_id)
                affection  = profile.get("affection_points", AFFECTION_DEFAULT)
                user_facts = profile.get("user_facts", [])
                history    = profile.get("messages", [])

                # ── Active trivia quest answer check ──────────────────────────
                if await self._check_quest_answer(message, user_id, user_name, user_prompt):
                    return

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

                # ── Context modifiers ─────────────────────────────────────────
                mod_parts: list[str] = []
                late_mod = _get_late_night_modifier()
                if late_mod:
                    mod_parts.append(late_mod)
                if message.guild:
                    pout_mod = await self._build_pout_modifier(
                        message.guild.id, user_id, user_name
                    )
                    if pout_mod:
                        mod_parts.append(pout_mod)
                extra_modifiers = "".join(mod_parts)

                # ── Build prompt ──────────────────────────────────────────────
                system_prompt   = build_system_prompt(user_name, affection, user_facts, extra_modifiers)
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
                if len(reply_text) > 4096:
                    reply_text = reply_text[:4093] + "…"

                # ── Visual engine: fetch tier gif + build embed ────────────────
                tier_key  = get_affection_tier(affection)
                gif_url   = await self._fetch_waifu_gif(tier_key)

                if gif_url:
                    try:
                        icon_url = self.bot.user.display_avatar.url
                    except Exception:
                        icon_url = None
                    embed = discord.Embed(
                        description=reply_text,
                        color=EMBED_COLORS.get(tier_key, 0xFFB6C1),
                    )
                    embed.set_author(name="Yua ✨", icon_url=icon_url)
                    embed.set_image(url=gif_url)
                    await message.reply(embed=embed)
                else:
                    # Fallback: plain text if waifu.pics unavailable
                    if len(reply_text) > 1990:
                        reply_text = reply_text[:1990] + "…"
                    await message.reply(reply_text)

                # ── Random quest trigger (10%) ─────────────────────────────────
                if random.random() < QUEST_CHANCE and user_id not in self._active_quests:
                    asyncio.create_task(
                        self._cmd_quest(message, user_id, user_name, user_facts)
                    )

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
