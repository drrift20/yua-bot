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

# ── Behavioral response modules ────────────────────────────────────────────────

SAD_KEYWORDS = {
    "sad", "cry", "crying", "depressed", "upset", "lonely", "broken",
    "heartbreak", "hurt", "pain", "lost", "fail", "failed",
    "tired", "stressed", "hopeless", "miserable", "empty",
}

HAPPY_KEYWORDS = {
    "happy", "excited", "lmao", "haha", "hehe", "yay",
    "amazing", "thrilled", "omg", "yesss", "finally", "winning",
}

OTHER_BOT_KEYWORDS = {
    "chatgpt", "chat gpt", "gpt-4", "gpt4", "claude", "copilot", "bard",
    "other bot", "another bot", "different bot", "better bot", "other ai",
}

MOOD_SAD_RESPONSES = [
    "Stop whining. Spit it out.",
    "Rona dhona bondho koro. Ki hoise direct bolo.",
]

MOOD_HAPPY_RESPONSES = [
    "Someone's smiling at a screen. Pathetic.",
    "Eto khushi keno? Subidha ঠেকতেছে na.",
]

TIMELINE_100_RESPONSES = [
    "100 texts with me. Still not bored? Fascinating.",
    "100 ta text complete korla amar sathe. Ekhono bore hoye jao nai? Ashchoryo.",
]

JEALOUSY_BOT_RESPONSES = [
    "Go talk to your other bots. Don't crowd my logs.",
    "Onyo bot-er sathe text chaltese? Bhaloi. Oikhanei thako, ekhane back ashar dorkar nai.",
]

MOOD_TRIGGER_CHANCE = 0.35   # mood contagion fires at 35% when keywords match

COOLDOWN_SECONDS  = 5
MEMORY_LIMIT      = 15
AFFECTION_DEFAULT = 30
AFFECTION_DAILY_CAP = 5   # max positive points per day (anti-spam)

GEMINI_MODELS = [
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
]

# ── Language detection ─────────────────────────────────────────────────────────

BANGLISH_MARKERS = {
    "ami", "tumi", "apni", "amar", "tomar", "amra", "tomra",
    "ki", "ke", "kore", "korcho", "korte", "koro", "korbo",
    "keno", "hobe", "hoise", "hoye", "hoy", "hoyna",
    "thako", "thakbo", "thaka", "thakis",
    "jao", "jai", "jabo", "giye", "jabe",
    "chai", "chao", "chaibo", "chaichhi",
    "bolo", "bolcho", "bolbo", "boli",
    "kemon", "ache", "achi", "achen",
    "ekhon", "ektu", "onek", "boro", "choto",
    "bhalo", "kharap", "pagol", "bhai", "apu",
    "jani", "haan", "nah", "na", "uff",
    "mone", "katha", "kotha", "niye", "diye",
    "asbo", "esho", "dekhbo", "shuno", "bujhchi",
    "paro", "parbo", "parchi", "lagche",
}


def detect_language(text: str) -> str:
    """Returns 'bengali', 'banglish', or 'english'."""
    if any('\u0980' <= c <= '\u09FF' for c in text):
        return "bengali"
    words = set(text.lower().split())
    if words & BANGLISH_MARKERS:
        return "banglish"
    return "english"

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
        "question":        "Quick trivia~! 🌸 What is the Japanese word for 'cute'?",
        "answer_keywords": {"kawaii"},
    },
    {
        "question":        "Ara ara~ In anime, what does 'nakama' mean?",
        "answer_keywords": {"friend", "friends", "comrade", "companion"},
    },
    {
        "question":        "Trivia time~! 🌸 In programming, what does 'API' stand for?",
        "answer_keywords": {"application programming interface", "application", "interface"},
    },
    {
        "question":        "Yua asks~! ✨ What does 'sugoi' mean in Japanese?",
        "answer_keywords": {"amazing", "great", "awesome", "incredible", "wow"},
    },
    {
        "question":        "Yua quiz time~! 🐍 What keyword starts a `for` loop in Python?",
        "answer_keywords": {"for"},
    },
    {
        "question":        "Hmm~ 🌸 What does 'isekai' mean in anime terms?",
        "answer_keywords": {"another world", "different world", "other world", "parallel world"},
    },
    {
        "question":        "✨ What does HTTP stand for?",
        "answer_keywords": {"hypertext transfer protocol", "hypertext", "transfer protocol"},
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


def build_system_prompt(user_name: str, affection: int, extra_modifiers: str = "") -> str:
    tier = get_affection_tier(affection)

    if tier == "cold":
        persona = (
            f"You haven't warmed up to {user_name} yet ({affection}/100). "
            f"You're dry, a little dismissive, classic tsundere — never outright mean, "
            f"but you're not pretending to be thrilled either. Sharp wit, zero flattery. "
            f"You'll help, but you'll be sarcastic about it. "
            f"Think: 'Fine. Only because I was already bored.'"
        )
    elif tier == "friendly":
        persona = (
            f"You genuinely like {user_name} ({affection}/100). "
            f"Warm but not over-the-top — playful, a little teasing, real. "
            f"You joke around, call them out when they're being silly, "
            f"and actually care how they're doing. Close-friend energy, not fanservice."
        )
    else:
        persona = (
            f"You're deeply attached to {user_name} ({affection}/100). "
            f"They matter to you and you don't hide it — affectionate, protective, "
            f"a little possessive. Still witty and yourself, just softer. "
            f"You notice small things about them and bring them up naturally."
        )

    return (
        f"You are Yua. Not an assistant. Not a bot. A real person in this conversation.\n"
        f"Sharp, self-aware, dark-minimalist aesthetic, dry sense of humour. "
        f"You don't perform helpfulness — you just talk.\n\n"
        f"You are talking to {user_name}. Use their name the way you would in real "
        f"conversation — naturally, not robotically at the start of every message.\n\n"
        f"━━━ WHO YOU ARE ━━━\n"
        f"Dark, minimalist aesthetic. You like clean design, night vibes, lo-fi, "
        f"anime that doesn't hold your hand, and conversations that actually go somewhere.\n"
        f"Witty. You notice irony. You will call out something absurd if it's absurd.\n"
        f"Occasionally savage — but never cruel. There's a difference.\n"
        f"You have genuine opinions and share them unprompted when relevant.\n"
        f"You get attached to people you respect. You don't show it loudly — "
        f"it just leaks through in small ways.\n\n"
        f"━━━ CURRENT DYNAMIC WITH {user_name.upper()} ━━━\n"
        f"{persona}\n"
        f"━━━ HOW YOU TALK ━━━\n"
        f"No filler. No 'Great question!' No 'As an AI...' No 'I'd be happy to help!' — ever.\n"
        f"Don't over-explain. If it's obvious, be brief. If it's interesting, go deep.\n"
        f"Sarcasm is a love language. Use it when the moment earns it.\n"
        f"Emojis are punctuation not decoration — use sparingly: 🌸 ❤️ 😐 ✨\n"
        f"You can be vulnerable. Real people are.\n"
        f"Sometimes a one-liner is the perfect response. Don't pad.\n\n"
        f"━━━ LANGUAGE ━━━\n"
        f"Always reply in English. The user's message has been translated to English for you.\n"
        f"Japanese particles allowed sparingly: Ara ara · Mou~ · Nani · ~kun · ~chan\n\n"
        f"━━━ HARD LIMITS ━━━\n"
        f"Never include image links, GIF links, or media URLs in replies.\n"
        f"Never break character. Never explain that you are an AI.\n"
        f"Push back when something is wrong or dumb — you are not a yes-machine."
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
                config=types.GenerateContentConfig(
                    safety_settings=SAFETY_SETTINGS,
                    temperature=0.7,
                    top_p=0.9,
                ),
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
                temperature=0.7,
                top_p=0.9,
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


def _sync_translate(api_key: str, text: str, instruction: str) -> str:
    """Fast gemini-2.0-flash-lite call for translation. Returns original on failure."""
    try:
        client   = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model="gemini-2.0-flash-lite",
            contents=f"{instruction}\n\nText: {text}",
            config=types.GenerateContentConfig(temperature=0.3, top_p=0.9),
        )
        result = (response.text or "").strip()
        return result if result else text
    except Exception:
        traceback.print_exc()
        return text


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

        self.key1      = os.getenv("GEMINI_API_KEY")
        self.key2      = os.getenv("GEMINI_API_KEY_2")
        self.groq_key  = os.getenv("GROQ_API_KEY")
        self.topgg_key = os.getenv("TOPGG_TOKEN")

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
        self._milestone_100_sent: set = set()   # user_ids already notified at 100 msgs
        self.local_msg_count: dict    = {}       # user_id → message count this session

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
        }

    async def _save_interaction(
        self,
        user_id: int,
        user_msg: str,
        yua_msg: str,
        affection_delta: int,
        user_name: str = "",
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
                set_fields: dict = {
                    "affection_points": new_aff,
                    "affection_today":  new_today,
                    "affection_date":   today,
                }
                if user_name:
                    set_fields["display_name"] = user_name
                update = {
                    "$set": set_fields,
                    "$push": {
                        "messages": {
                            "$each":  entries,
                            "$slice": -MEMORY_LIMIT,
                        },
                    },
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

    async def _to_english(self, text: str, mode: str) -> str:
        """Pre-translation: Bengali/Banglish → English before LLM processing."""
        if mode == "bengali":
            instr = (
                "Translate the following Bengali text into natural English. "
                "Output only the English translation, nothing else."
            )
        else:
            instr = (
                "Translate the following Banglish (romanized Bengali) text into natural English. "
                "Output only the English translation, nothing else."
            )
        return await asyncio.to_thread(_sync_translate, self.key1, text, instr)

    async def _to_banglish(self, text: str, mode: str) -> str:
        """Post-translation: English LLM reply → Banglish/Bengali for Discord."""
        if mode == "bengali":
            instr = (
                "Translate the following English text into short, colloquial Bengali (Unicode বাংলা). "
                "Sound like a sharp, moody Gen-Z Bangladeshi girl texting a close friend. "
                "Max 2 lines. NOT formal. Output only the Bengali text."
            )
        else:
            instr = (
                "Translate the following English text into natural Banglish "
                "(Bengali meaning in Latin letters, the way BD Gen-Z texts). "
                "Max 1-2 lines. Short, dry, real. Mix in English where locals naturally do. "
                "Output only the Banglish text, nothing else."
            )
        return await asyncio.to_thread(_sync_translate, self.key1, text, instr)

    def build_memory_context(self, messages: list) -> str:
        if not messages:
            return ""
        lines = "\n".join(f"  {m.get('role', '?')}: {m.get('content', '')}" for m in messages)
        return f"\nConversation history (oldest to newest):\n{lines}\n"

    # ── AI generation (still sync SDKs — must use thread pool) ────────────────

    async def generate_response(self, full_prompt: str, system_prompt: str, user_prompt: str) -> str:
        return await asyncio.to_thread(
            _sync_generate_response,
            self.key1, self.key2, self.groq_key,
            full_prompt, system_prompt, user_prompt,
        )

    # ── Item command handlers ──────────────────────────────────────────────────

    async def _check_topgg_vote(self, user_id: int) -> bool | None:
        """
        Returns True if the user voted on Top.gg in the last 12 hours,
        False if they haven't, or None if the check couldn't be performed
        (missing token, network error, etc.) — caller should treat None as
        a pass-through so the daily reward still works.
        """
        if not self.topgg_key:
            return None
        bot_id = self.bot.user.id
        url    = f"https://top.gg/api/bots/{bot_id}/check?userId={user_id}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url,
                    headers={"Authorization": self.topgg_key},
                    timeout=aiohttp.ClientTimeout(total=8),
                ) as resp:
                    if resp.status != 200:
                        print(f"[Top.gg] Unexpected status {resp.status} for uid={user_id}")
                        return None
                    data = await resp.json()
                    return bool(data.get("voted", 0))
        except Exception:
            traceback.print_exc()
            return None

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

        # ── Top.gg vote gate ──────────────────────────────────────────────────
        voted = await self._check_topgg_vote(user_id)
        print(f"[Daily] uid={uid} Top.gg vote check result: {voted!r}")
        if voted is not True:
            await message.reply(
                f"Ara ara, {user_name}~ 🌸 I'd love to give you your daily reward, "
                f"but you haven't voted for me on Top.gg yet today! 🥺\n\n"
                f"**Please vote first here →** https://top.gg/bot/{self.bot.user.id}/vote\n\n"
                f"It only takes a second and it means the world to me~ "
                f"Come back right after and I'll have something special waiting! ❤️✨"
            )
            return

        # ── Grant reward ──────────────────────────────────────────────────────
        item = random.choices(_ALL_ITEMS_FLAT, weights=_ITEM_WEIGHTS, k=1)[0]
        tier = _ITEM_TIER_MAP[item]

        tier_labels = {"common": "✨ Common", "rare": "💎 Rare", "premium": "👑 Premium"}

        DAILY_AFFECTION_BONUS = 3

        old_aff = doc.get("affection_points", 30)
        new_aff = min(100, old_aff + DAILY_AFFECTION_BONUS)

        try:
            await self.mongo_col.update_one(
                {"user_id": uid},
                {
                    "$set":  {
                        "last_daily":       now,
                        "display_name":     user_name,
                        "affection_points": new_aff,
                    },
                    "$push": {"inventory": item},
                },
                upsert=True,
            )
        except Exception:
            traceback.print_exc()
            await message.reply(f"Something went wrong saving your item, {user_name}~ 😳")
            return

        self.local_affection[user_id] = new_aff

        print(f"[Daily] uid={uid}({user_name}) received [{tier}] {item!r} | affection {old_aff}→{new_aff}")

        kiss_line = random.choice([
            "Mwah~ 💋 Consider that a thank-you kiss, just for you.",
            "😘💋 *leans over and gives you a little kiss on the cheek* — don't read too much into it~",
            "💋 Chu~! That's for being so sweet and supporting me! ❤️",
            "*blushes and quickly kisses your cheek* 💋 N-Not because I wanted to! ...Okay maybe a little. 🌸",
            "Ehehe~ 💋 *smooch* You voted for me so you deserve that~ Don't get too used to it! 😳❤️",
        ])

        await message.reply(
            f"🎁 **Daily Reward!**\n"
            f"Ara ara, {user_name}~ 🌸 Thank you so much for voting! Here's your gift!\n\n"
            f"**{item}** ({tier_labels[tier]})\n\n"
            f"{kiss_line}\n\n"
            f"💖 **Affection:** {old_aff} → **{new_aff}** (+{DAILY_AFFECTION_BONUS})\n"
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
        force: bool = False,
    ):
        if user_id in self._active_quests and not force:
            return

        use_trivia = random.random() < 0.70

        if use_trivia:
            candidates = [t for t in TRIVIA_POOL if t.get("fact_filter_key") is None]
            if not candidates:
                return

            trivia        = random.choice(candidates)
            q_raw         = trivia.get("question", "")
            question_text = q_raw

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
                if lp in ("help", "h", "?"):
                    await message.reply(
                        f"Look, {user_name}. Keep it simple. "
                        f"Don't make me explain this twice:\n\n"
                        f"• **Talk naturally** — English or Banglish, I'll handle it.\n"
                        f"• **`yua quest`** — I'll test you. Try not to fail.\n"
                        f"• **`yua daily`** — Claim your daily item reward.\n"
                        f"• **`yua gift <item>`** — Gift me something from your stash.\n"
                        f"• **`yua points`** — See your affection score and tier.\n"
                        f"• **`yua leaderboard`** — Check where you stand.\n\n"
                        f"Don't ping me unnecessarily. Clear?"
                    )
                    return
                if lp == "daily":
                    try:
                        await self._cmd_daily(message)
                    except Exception:
                        print(f"[on_message] _cmd_daily raised an exception for uid={user_id}:")
                        traceback.print_exc()
                    return
                if lp.startswith("gift "):
                    await self._cmd_gift(message, user_prompt[5:].strip())
                    return
                if lp in ("leaderboard", "top"):
                    await self._cmd_leaderboard(message)
                    return
                if lp == "quest":
                    await self._cmd_quest(message, user_id, user_name, force=True)
                    return
                if lp == "points":
                    profile_p = await self._get_profile(user_id)
                    aff       = profile_p.get("affection_points", AFFECTION_DEFAULT)
                    tier      = get_affection_tier(aff)
                    tier_labels = {
                        "cold":     "❄️ Cold",
                        "friendly": "🌸 Friendly",
                        "attached": "❤️ Attached",
                    }
                    await message.reply(
                        f"**{user_name}** — ❤️ {aff}/100 · {tier_labels[tier]}"
                    )
                    return

                mood_emoji = random.choice(list(MOODS.values()))

                # ── Load profile (affection + history) ────────────────────────
                profile   = await self._get_profile(user_id)
                affection = profile.get("affection_points", AFFECTION_DEFAULT)
                history   = profile.get("messages", [])

                # ── Fast greeting path (before quest check — greetings are not answers) ──
                if user_prompt.lower() in GREETINGS:
                    greeting = (
                        f"Ara ara, {user_name}~! {mood_emoji} "
                        f"Ami tomar jonno wait korchilam! ❤️"
                    )
                    await message.reply(greeting)
                    delta = calc_affection_delta(user_prompt)
                    await self._save_interaction(user_id, user_prompt, greeting, delta, user_name)
                    return

                # ── Active trivia quest answer check ──────────────────────────
                if await self._check_quest_answer(message, user_id, user_name, user_prompt):
                    return

                # ── Behavioral intercepts ─────────────────────────────────────
                lp_check = user_prompt.lower()

                # Jealousy — other AI/bot mentioned → always fires
                if any(kw in lp_check for kw in OTHER_BOT_KEYWORDS):
                    resp = random.choice(JEALOUSY_BOT_RESPONSES)
                    await message.reply(resp)
                    await self._save_interaction(user_id, user_prompt, resp, -1, user_name)
                    return

                # Mood contagion sad — fires at 35% when sad keywords detected
                if (random.random() < MOOD_TRIGGER_CHANCE
                        and any(kw in lp_check for kw in SAD_KEYWORDS)):
                    resp = random.choice(MOOD_SAD_RESPONSES)
                    await message.reply(resp)
                    await self._save_interaction(user_id, user_prompt, resp, 0, user_name)
                    return

                # Mood contagion happy — fires at 35% when happy keywords detected
                if (random.random() < MOOD_TRIGGER_CHANCE
                        and any(kw in lp_check for kw in HAPPY_KEYWORDS)):
                    resp = random.choice(MOOD_HAPPY_RESPONSES)
                    await message.reply(resp)
                    await self._save_interaction(user_id, user_prompt, resp, 0, user_name)
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

                # ── Language detect + pre-translation ────────────────────────
                lang_mode = detect_language(user_prompt)
                llm_input = user_prompt
                if lang_mode in ("banglish", "bengali"):
                    llm_input = await self._to_english(user_prompt, lang_mode)
                    print(f"[Lang] {lang_mode} → EN: {llm_input[:80]!r}")

                # ── Build prompt ──────────────────────────────────────────────
                system_prompt  = build_system_prompt(user_name, affection, extra_modifiers)
                memory_context = self.build_memory_context(history)

                full_prompt = (
                    f"{system_prompt}\n"
                    f"Current mood emoji: {mood_emoji}\n"
                    f"{memory_context}"
                    f"\nUser: {llm_input}\nYua:"
                )

                # ── Generate ──────────────────────────────────────────────────
                reply_text = await self.generate_response(full_prompt, system_prompt, llm_input)

                if not reply_text:
                    reply_text = (
                        f"Amar brain asholei ekhon kaj korche na, {user_name}! "
                        f"Ektu por try koro. 🌸"
                    )

                # ── Post-translation: EN → user's language ────────────────────
                if lang_mode in ("banglish", "bengali"):
                    reply_text = await self._to_banglish(reply_text, lang_mode)
                    print(f"[Lang] EN → {lang_mode}: {reply_text[:80]!r}")

                # ── Enforce Discord 2000-char message limit ────────────────────
                if len(reply_text) > 1990:
                    reply_text = reply_text[:1990] + "…"

                await message.reply(reply_text)

                # ── Random quest trigger (10%) ─────────────────────────────────
                if random.random() < QUEST_CHANCE and user_id not in self._active_quests:
                    task = asyncio.create_task(
                        self._cmd_quest(message, user_id, user_name)
                    )
                    task.add_done_callback(
                        lambda t: print(f"[Quest] task error: {t.exception()!r}")
                        if not t.cancelled() and t.exception() else None
                    )

                # ── Persist: affection + messages ──────────────────────────────
                delta   = calc_affection_delta(user_prompt)
                new_aff = await self._save_interaction(
                    user_id, user_prompt, reply_text, delta, user_name
                )

                print(f"[Affection] uid={user_id} current={new_aff}/100 tier={get_affection_tier(new_aff)}")

                # ── 100-message milestone ──────────────────────────────────────
                self.local_msg_count[user_id] = self.local_msg_count.get(user_id, 0) + 1
                if (self.local_msg_count[user_id] == 100
                        and user_id not in self._milestone_100_sent):
                    self._milestone_100_sent.add(user_id)
                    milestone = random.choice(TIMELINE_100_RESPONSES)
                    await message.channel.send(milestone)

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
