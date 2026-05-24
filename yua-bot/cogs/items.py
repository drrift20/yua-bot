import discord
from discord.ext import commands
from discord import app_commands
from motor.motor_asyncio import AsyncIOMotorClient
import traceback
import random
import time
import os

# ── Item catalogue ──────────────────────────────────────────────────────────

ITEMS = {
    "common": [
        "Common Chocolate",
        "Common Pocky",
        "Common Candy",
        "Common Cookie",
    ],
    "rare": [
        "Rare Flower",
        "Rare Plushie",
        "Rare Perfume",
        "Rare Hairpin",
    ],
    "premium": [
        "Premium Coffee",
        "Premium Matcha",
        "Premium Ribbon",
        "Premium Headband",
    ],
}

ALL_ITEMS_FLAT = ITEMS["common"] + ITEMS["rare"] + ITEMS["premium"]

ITEM_WEIGHTS = (
    [60] * len(ITEMS["common"])
    + [30] * len(ITEMS["rare"])
    + [10] * len(ITEMS["premium"])
)

GIFT_AFFECTION = {
    "common":  3,
    "rare":    7,
    "premium": 10,
}

GIFT_REACTIONS = {
    "common": (
        "Ara ara, {name}~ 🌸 A {item}?  That's actually kinda sweet! "
        "Affection +{boost}~ ❤️"
    ),
    "rare": (
        "Kyaa~! {name}, a {item} just for me?! 😳✨ "
        "My heart is pounding! Affection +{boost}~ ❤️❤️"
    ),
    "premium": (
        "M-Mou, {name}! A {item}?! Daisuki~! 🌸❤️ "
        "I'll treasure this forever! Affection +{boost}~ ❤️❤️❤️"
    ),
}

DAILY_COOLDOWN = 86_400  # seconds (24 hours)


def _get_item_tier(item_name: str) -> str | None:
    for tier, names in ITEMS.items():
        if item_name in names:
            return tier
    return None


# ── Cog ─────────────────────────────────────────────────────────────────────

class Items(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.mongo_col = None
        mongo_uri = os.getenv("MONGO_URI")
        if mongo_uri:
            try:
                client = AsyncIOMotorClient(mongo_uri, serverSelectionTimeoutMS=5000)
                db = client["yua_bot"]
                self.mongo_col = db["users"]
                print("[Items] Motor MongoDB client ready.")
            except Exception:
                print("[Items] Motor MongoDB init failed:")
                traceback.print_exc()
        else:
            print("[Items] MONGO_URI not set — item commands will not persist.")

    # ── Internal DB helpers ──────────────────────────────────────────────────

    async def _get_doc(self, user_id: int) -> dict:
        uid = str(user_id)
        if self.mongo_col is not None:
            try:
                doc = await self.mongo_col.find_one({"user_id": uid})
                if doc:
                    return doc
            except Exception:
                print(f"[Items] _get_doc error uid={uid}:")
                traceback.print_exc()
        return {"user_id": uid, "inventory": [], "last_daily": 0, "affection_points": 30}

    async def _upsert(self, user_id: int, update: dict):
        if self.mongo_col is None:
            return
        uid = str(user_id)
        try:
            await self.mongo_col.update_one({"user_id": uid}, update, upsert=True)
        except Exception:
            print(f"[Items] _upsert error uid={uid}:")
            traceback.print_exc()

    # ── /daily ───────────────────────────────────────────────────────────────

    @app_commands.command(name="daily", description="Claim your daily item reward!")
    async def daily(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=False)

        user_id   = interaction.user.id
        user_name = interaction.user.display_name
        doc       = await self._get_doc(user_id)

        last_daily = doc.get("last_daily", 0)
        now        = time.time()
        elapsed    = now - last_daily

        if elapsed < DAILY_COOLDOWN:
            remaining = DAILY_COOLDOWN - elapsed
            hours, rem = divmod(int(remaining), 3600)
            mins       = rem // 60
            await interaction.followup.send(
                f"Mou, {user_name}~ 😳 You already claimed today! "
                f"Come back in **{hours}h {mins}m**. I'll be waiting~ 🌸"
            )
            return

        item = random.choices(ALL_ITEMS_FLAT, weights=ITEM_WEIGHTS, k=1)[0]
        tier = _get_item_tier(item)

        tier_labels = {"common": "✨ Common", "rare": "💎 Rare", "premium": "👑 Premium"}
        tier_label  = tier_labels.get(tier, tier)

        await self._upsert(user_id, {
            "$set":  {"last_daily": now, "display_name": user_name},
            "$push": {"inventory": item},
        })

        print(f"[Daily] uid={user_id}({user_name}) received [{tier}] {item!r}")

        embed = discord.Embed(
            title="🎁 Daily Reward!",
            description=(
                f"Ara ara, {user_name}~ 🌸 Here's your gift for today!\n\n"
                f"**{item}** ({tier_label})\n\n"
                f"Use `/gift {item}` to give it to me~ ❤️"
            ),
            color=0xFFB6C1,
        )
        embed.set_footer(text="Come back in 24 hours for your next reward!")
        await interaction.followup.send(embed=embed)

    # ── /gift ────────────────────────────────────────────────────────────────

    @app_commands.command(name="gift", description="Gift an item from your inventory to Yua!")
    @app_commands.describe(item_name="The exact name of the item you want to gift")
    async def gift(self, interaction: discord.Interaction, item_name: str):
        await interaction.response.defer(ephemeral=False)

        user_id   = interaction.user.id
        user_name = interaction.user.display_name
        doc       = await self._get_doc(user_id)

        inventory: list = doc.get("inventory", [])

        if item_name not in inventory:
            inv_display = ", ".join(f"**{i}**" for i in inventory) if inventory else "*empty*"
            await interaction.followup.send(
                f"Hmm, {user_name}~ 🌸 You don't have **{item_name}** in your inventory!\n"
                f"Your items: {inv_display}"
            )
            return

        tier = _get_item_tier(item_name)
        if tier is None:
            await interaction.followup.send(
                f"That doesn't look like a valid item, {user_name}~ 😳"
            )
            return

        boost = GIFT_AFFECTION[tier]

        # Remove one instance of the item from inventory
        inventory_copy = inventory.copy()
        inventory_copy.remove(item_name)

        old_aff = doc.get("affection_points", 30)
        new_aff = min(100, old_aff + boost)

        await self._upsert(user_id, {
            "$set": {
                "inventory":       inventory_copy,
                "affection_points": new_aff,
                "display_name":    user_name,
            },
        })

        print(
            f"[Gift] uid={user_id}({user_name}) gifted [{tier}] {item_name!r} "
            f"affection {old_aff}→{new_aff} (+{boost})"
        )

        reaction_template = GIFT_REACTIONS[tier]
        reaction = reaction_template.format(name=user_name, item=item_name, boost=boost)

        tier_colors = {"common": 0xFFB6C1, "rare": 0xC084FC, "premium": 0xFFD700}
        embed = discord.Embed(
            title="💝 Gift Received!",
            description=reaction,
            color=tier_colors.get(tier, 0xFFB6C1),
        )
        embed.add_field(
            name="Affection",
            value=f"{old_aff} → **{new_aff}**/100 (+{boost})",
            inline=True,
        )
        await interaction.followup.send(embed=embed)

    # ── /leaderboard ─────────────────────────────────────────────────────────

    @app_commands.command(name="leaderboard", description="Top 10 users by affection points!")
    async def leaderboard(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=False)

        if self.mongo_col is None:
            await interaction.followup.send(
                "Gomen, MongoDB isn't connected so I can't show the leaderboard~ 😳"
            )
            return

        try:
            cursor = self.mongo_col.find(
                {"affection_points": {"$exists": True}},
                {"user_id": 1, "affection_points": 1, "display_name": 1},
            ).sort("affection_points", -1).limit(10)

            top_users = await cursor.to_list(length=10)
        except Exception:
            print("[Leaderboard] DB query error:")
            traceback.print_exc()
            await interaction.followup.send(
                "Something went wrong fetching the leaderboard~ 😳 Try again later!"
            )
            return

        if not top_users:
            await interaction.followup.send(
                "No data yet~ 🌸 Start chatting with me to appear on the leaderboard!"
            )
            return

        medal = {1: "🥇", 2: "🥈", 3: "🥉"}
        lines = []

        for rank, entry in enumerate(top_users, start=1):
            uid          = int(entry["user_id"])
            stored_name  = entry.get("display_name", f"User {uid}")
            affection    = entry.get("affection_points", 0)

            # Try to resolve a fresh display name from the guild
            display_name = stored_name
            if interaction.guild:
                member = interaction.guild.get_member(uid)
                if member is None:
                    try:
                        member = await interaction.guild.fetch_member(uid)
                    except Exception:
                        pass
                if member:
                    display_name = member.display_name

            prefix = medal.get(rank, f"**#{rank}**")
            lines.append(f"{prefix} {display_name} — ❤️ {affection}/100")

        embed = discord.Embed(
            title="🌸 Affection Leaderboard 🌸",
            description="\n".join(lines),
            color=0xFFB6C1,
        )
        embed.set_footer(text="Chat with Yua and send gifts to climb the ranks~")
        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Items(bot))
