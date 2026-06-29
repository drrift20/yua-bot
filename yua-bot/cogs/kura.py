import discord
from discord.ext import commands
from motor.motor_asyncio import AsyncIOMotorClient
from collections import Counter
import traceback
import os

# ── Constants (mirrors chat.py) ────────────────────────────────────────────────

ITEM_CATALOGUE = {
    "common":  ["Common Chocolate", "Common Pocky", "Common Candy", "Common Cookie"],
    "rare":    ["Rare Flower", "Rare Plushie", "Rare Perfume", "Rare Hairpin"],
    "premium": ["Premium Coffee", "Premium Matcha", "Premium Ribbon", "Premium Headband"],
}
_ITEM_TIER_MAP = {
    item: tier
    for tier, items in ITEM_CATALOGUE.items()
    for item in items
}
GIFT_AFFECTION = {"common": 3, "rare": 7, "premium": 10}
AFFECTION_DEFAULT = 30

TIER_EMOJI = {"common": "✨", "rare": "💎", "premium": "👑"}
TIER_COLOUR = {"common": 0xFFD700, "rare": 0x9B59B6, "premium": 0xFF1493}

# Responses keyed by (affection_tier, item_tier)
KURA_GIFT_REPLIES = {
    # ── Cold (0-25) ──────────────────────────────────────────────────────────
    ("cold", "common"): (
        "A {item}. Fine. I'll add it to the pile. "
        "Don't expect applause. +{boost} affection."
    ),
    ("cold", "rare"): (
        "...That's actually— whatever. I'll take it. "
        "Not like I'm impressed or anything. +{boost}."
    ),
    ("cold", "premium"): (
        "A {item}. Don't think this changes anything between us. "
        "...Thank you. +{boost}."
    ),
    # ── Friendly (26-65) ─────────────────────────────────────────────────────
    ("friendly", "common"): (
        "Ara ara, {name}~ 🌸 A {item}? That's actually kinda sweet! "
        "Affection +{boost}~ ❤️"
    ),
    ("friendly", "rare"): (
        "Kyaa~! {name}, a {item} just for me?! 😳✨ "
        "My heart is pounding! Affection +{boost}~ ❤️❤️"
    ),
    ("friendly", "premium"): (
        "M-Mou, {name}!! A {item}?! Daisuki~! 🌸❤️ "
        "I'll treasure this forever! Affection +{boost}~ ❤️❤️❤️"
    ),
    # ── Attached (66-100) ────────────────────────────────────────────────────
    ("attached", "common"): (
        "Kyaa~ {name}-kun, you're always thinking of me! 🌸 "
        "Even little {item} makes me so happy~ +{boost}! ❤️"
    ),
    ("attached", "rare"): (
        "Mou, {name}!! A {item}?! You're making my heart flutter again~ 😳❤️ "
        "Daisuki~! +{boost}! ❤️❤️"
    ),
    ("attached", "premium"): (
        "A-ARA ARA~!! {name}-senpai!! A {item}?! 💋🌸 "
        "I'll treasure this FOREVER, I promise!! Daisuki daisuki daisuki~! +{boost}! ❤️❤️❤️"
    ),
}


def _affection_tier(points: int) -> str:
    if points <= 25:
        return "cold"
    elif points <= 65:
        return "friendly"
    return "attached"


def _build_inventory_embed(user_name: str, inventory: list, affection: int) -> discord.Embed:
    """Build a Kura inventory embed from a raw list of item strings."""
    counts = Counter(inventory)
    tier = _affection_tier(affection)

    if not counts:
        if tier == "cold":
            desc = "Your Kura is empty. Not surprised."
        elif tier == "friendly":
            desc = f"Nothing in here yet, {user_name}~ 🌸 Try `yua daily` to get started!"
        else:
            desc = (
                f"Mou, {user_name}-kun~ 😳 Your Kura is completely empty! "
                f"Claim `yua daily` and fill it up for me~ ❤️"
            )
        return discord.Embed(
            title="🗄️ Kura — Item Storage",
            description=desc,
            color=0x2C2F33,
        )

    # Group items by tier for display
    sections: dict[str, list[str]] = {"common": [], "rare": [], "premium": []}
    unknown: list[str] = []
    for item, qty in sorted(counts.items()):
        t = _ITEM_TIER_MAP.get(item)
        if t:
            emoji = TIER_EMOJI[t]
            sections[t].append(f"{emoji} **{item}** × {qty}")
        else:
            unknown.append(f"• {item} × {qty}")

    embed = discord.Embed(
        title=f"🗄️ {user_name}'s Kura",
        color=0xFF69B4 if tier == "attached" else (0x9B59B6 if tier == "friendly" else 0x2C2F33),
    )

    if sections["premium"]:
        embed.add_field(name="👑 Premium", value="\n".join(sections["premium"]), inline=False)
    if sections["rare"]:
        embed.add_field(name="💎 Rare", value="\n".join(sections["rare"]), inline=False)
    if sections["common"]:
        embed.add_field(name="✨ Common", value="\n".join(sections["common"]), inline=False)
    if unknown:
        embed.add_field(name="📦 Other", value="\n".join(unknown), inline=False)

    total = sum(counts.values())
    embed.set_footer(text=f"Total items: {total}  •  Use 'yua kura gift <item>' to give Yua something~ ❤️")
    return embed


# ── Cog ───────────────────────────────────────────────────────────────────────

class Kura(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.mongo_col = None

        mongo_uri = os.getenv("MONGO_URI")
        if mongo_uri:
            try:
                client = AsyncIOMotorClient(mongo_uri, serverSelectionTimeoutMS=5000)
                self.mongo_col = client["yua_bot"]["users"]
                print("[Kura] Motor MongoDB client ready.")
            except Exception:
                print("[Kura] MongoDB init failed — Kura commands need MongoDB to work:")
                traceback.print_exc()
        else:
            print("[Kura] MONGO_URI not set — Kura commands require MongoDB.")

    # ── DB helpers ─────────────────────────────────────────────────────────────

    async def _get_doc(self, user_id: int) -> dict:
        uid = str(user_id)
        if self.mongo_col is not None:
            try:
                doc = await self.mongo_col.find_one({"user_id": uid})
                return doc or {}
            except Exception:
                print(f"[Kura/DB] _get_doc error uid={uid}:")
                traceback.print_exc()
        return {}

    async def _require_mongo(self, message: discord.Message, user_name: str) -> bool:
        """Returns True if mongo is available, sends error and returns False if not."""
        if self.mongo_col is None:
            await message.reply(
                f"Gomen, {user_name}~ 😳 "
                f"MongoDB isn't connected so Kura can't work right now."
            )
            return False
        return True

    # ── Command handlers ───────────────────────────────────────────────────────

    async def cmd_show(self, message: discord.Message, user_id: int, user_name: str):
        """yua kura — show inventory embed."""
        if not await self._require_mongo(message, user_name):
            return

        doc       = await self._get_doc(user_id)
        inventory = doc.get("inventory", [])
        affection = doc.get("affection_points", AFFECTION_DEFAULT)

        embed = _build_inventory_embed(user_name, inventory, affection)
        await message.reply(embed=embed)
        print(f"[Kura] Show uid={user_id}({user_name}) items={len(inventory)}")

    async def cmd_gift(
        self,
        message: discord.Message,
        user_id: int,
        user_name: str,
        item_name: str,
    ):
        """yua kura gift <item> — gift an item to Yua for affection."""
        if not await self._require_mongo(message, user_name):
            return

        if not item_name:
            await message.reply(
                f"Nani, {user_name}~ 😳 What do you want to gift me?\n"
                f"Try: `yua kura gift <item name>`"
            )
            return

        doc       = await self._get_doc(user_id)
        inventory = doc.get("inventory", [])

        # Case-insensitive item lookup
        matched = next(
            (i for i in inventory if i.lower() == item_name.lower()),
            None,
        )
        if matched is None:
            if inventory:
                counts  = Counter(inventory)
                preview = "\n".join(f"  • {i} × {q}" for i, q in sorted(counts.items()))
                await message.reply(
                    f"Hmm, {user_name}~ 🌸 You don't have **{item_name}** in your Kura!\n\n"
                    f"**Your items:**\n{preview}"
                )
            else:
                await message.reply(
                    f"Hmm, {user_name}~ 🌸 Your Kura is empty! "
                    f"Try `yua daily` first ❤️"
                )
            return

        item_tier = _ITEM_TIER_MAP.get(matched)
        if item_tier is None:
            await message.reply(
                f"That doesn't look like a valid Kura item, {user_name}~ 😳"
            )
            return

        boost   = GIFT_AFFECTION[item_tier]
        old_aff = doc.get("affection_points", AFFECTION_DEFAULT)
        new_aff = min(100, old_aff + boost)
        aff_tier = _affection_tier(old_aff)

        # Remove one instance of the item from inventory list
        inventory_copy = inventory.copy()
        inventory_copy.remove(matched)

        try:
            await self.mongo_col.update_one(
                {"user_id": str(user_id)},
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
            await message.reply(f"Something went wrong saving your gift, {user_name}~ 😳")
            return

        print(
            f"[Kura] Gift uid={user_id}({user_name}) [{item_tier}] {matched!r} "
            f"aff {old_aff}→{new_aff} (+{boost})"
        )

        reply_template = KURA_GIFT_REPLIES.get(
            (aff_tier, item_tier),
            KURA_GIFT_REPLIES[("friendly", item_tier)],
        )
        reply = reply_template.format(name=user_name, item=matched, boost=boost)
        await message.reply(
            f"{reply}\n"
            f"*(Affection: {old_aff} → **{new_aff}**/100)*"
        )

    async def cmd_give(
        self,
        message: discord.Message,
        user_id: int,
        user_name: str,
        item_name: str,
    ):
        """yua kura give @user <item> — give an item to another user."""
        if not await self._require_mongo(message, user_name):
            return

        if not message.mentions:
            await message.reply(
                f"Nani, {user_name}~ 😳 Who are you giving it to?\n"
                f"Try: `yua kura give @user <item name>`"
            )
            return

        target = message.mentions[0]

        if target.bot:
            await message.reply(
                f"Bots don't need Kura items, {user_name}. Think about it."
            )
            return

        if target.id == user_id:
            await message.reply(
                f"...You're trying to give it to yourself, {user_name}. "
                f"That's not how this works."
            )
            return

        if not item_name:
            await message.reply(
                f"Nani, {user_name}~ 😳 What item do you want to give?\n"
                f"Try: `yua kura give @user <item name>`"
            )
            return

        doc       = await self._get_doc(user_id)
        inventory = doc.get("inventory", [])

        # Case-insensitive lookup
        matched = next(
            (i for i in inventory if i.lower() == item_name.lower()),
            None,
        )
        if matched is None:
            if inventory:
                counts  = Counter(inventory)
                preview = "\n".join(f"  • {i} × {q}" for i, q in sorted(counts.items()))
                await message.reply(
                    f"Hmm, {user_name}~ 🌸 You don't have **{item_name}** in your Kura!\n\n"
                    f"**Your items:**\n{preview}"
                )
            else:
                await message.reply(
                    f"Your Kura is empty, {user_name}. Nothing to give."
                )
            return

        # Remove from sender
        sender_inv = inventory.copy()
        sender_inv.remove(matched)

        try:
            # Deduct from sender
            await self.mongo_col.update_one(
                {"user_id": str(user_id)},
                {"$set": {"inventory": sender_inv}},
                upsert=True,
            )
            # Add to receiver
            await self.mongo_col.update_one(
                {"user_id": str(target.id)},
                {
                    "$push":        {"inventory": matched},
                    "$setOnInsert": {"affection_points": AFFECTION_DEFAULT},
                },
                upsert=True,
            )
        except Exception:
            traceback.print_exc()
            await message.reply(f"Something went wrong with the transfer, {user_name}~ 😳")
            return

        print(
            f"[Kura] Give uid={user_id}({user_name}) → uid={target.id}({target.display_name}) "
            f"item={matched!r}"
        )
        await message.reply(
            f"Done. **{matched}** has been moved from your Kura to "
            f"**{target.display_name}**'s Kura. 📦"
        )

    # ── Dispatcher (called from chat.py's on_message) ──────────────────────────

    async def dispatch(
        self,
        message: discord.Message,
        user_id: int,
        user_name: str,
        sub: str,          # everything after "kura" (stripped, lowercased)
        original: str,     # original-case text after "kura" (for item name)
    ):
        """Route kura sub-commands."""
        if not sub:
            await self.cmd_show(message, user_id, user_name)
            return

        # kura gift <item>
        if sub.startswith("gift"):
            item_raw = original[4:].strip() if len(original) > 4 else ""
            await self.cmd_gift(message, user_id, user_name, item_raw)
            return

        # kura give @user <item>
        if sub.startswith("give"):
            # Strip mention token(s) from original to isolate item name
            rest = original[4:].strip()          # after "give"
            item_raw = rest
            for m in message.mentions:
                # Remove <@id> and <@!id> variants
                item_raw = item_raw.replace(f"<@{m.id}>", "").replace(f"<@!{m.id}>", "")
            item_raw = item_raw.strip()
            await self.cmd_give(message, user_id, user_name, item_raw)
            return

        # Unknown sub-command
        await message.reply(
            f"Nani, {user_name}~ 😳 That's not a valid Kura command.\n"
            f"Try: `yua kura` · `yua kura gift <item>` · `yua kura give @user <item>`"
        )


async def setup(bot):
    await bot.add_cog(Kura(bot))
