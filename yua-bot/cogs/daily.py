import discord
from discord.ext import commands
from motor.motor_asyncio import AsyncIOMotorClient
import aiohttp
import os
import traceback
from datetime import datetime, timezone, timedelta

DAILY_COOLDOWN_HOURS = 24
AFFECTION_BONUS      = 8   # affection gained on successful daily claim
AFFECTION_DEFAULT    = 30

TOPGG_CHECK_URL = "https://top.gg/api/bots/{bot_id}/check"


# ── Helpers ────────────────────────────────────────────────────────────────────

def _affection_bar(points: int) -> str:
    """Simple 10-block visual bar for affection score."""
    filled = round(points / 10)
    empty  = 10 - filled
    return "❤️" * filled + "🖤" * empty


async def _check_topgg_vote(session: aiohttp.ClientSession, token: str, bot_id: int, user_id: int) -> bool:
    """
    Returns True if the user voted on Top.gg within the last 12 hours.
    Returns False on any error (fail-open so the bot works without Top.gg).
    """
    url     = TOPGG_CHECK_URL.format(bot_id=bot_id)
    headers = {"Authorization": token}
    params  = {"userId": str(user_id)}
    try:
        async with session.get(url, headers=headers, params=params, timeout=aiohttp.ClientTimeout(total=6)) as resp:
            if resp.status == 200:
                data = await resp.json()
                return bool(data.get("voted", 0))
            print(f"[Top.gg] Unexpected status {resp.status}")
            return False
    except Exception:
        print("[Top.gg] Vote check failed:")
        traceback.print_exc()
        return False


# ── Cog ────────────────────────────────────────────────────────────────────────

class Daily(commands.Cog):
    def __init__(self, bot):
        self.bot      = bot
        self.mongo_col = None

        mongo_uri = os.getenv("MONGO_URI")
        if mongo_uri:
            try:
                client         = AsyncIOMotorClient(mongo_uri, serverSelectionTimeoutMS=5000)
                db             = client["yua_bot"]
                self.mongo_col = db["users"]
                print("[Daily] Motor MongoDB client ready.")
            except Exception:
                print("[Daily] MongoDB init failed — in-memory fallback:")
                traceback.print_exc()
        else:
            print("[Daily] MONGO_URI not set — daily rewards won't persist across restarts.")

        # In-memory fallback (process-lifetime only)
        self._local: dict = {}   # user_id → {"last_daily": datetime, "affection": int}

    # ── DB helpers ─────────────────────────────────────────────────────────────

    async def _get_profile(self, user_id: int) -> dict:
        uid = str(user_id)
        if self.mongo_col is not None:
            try:
                doc = await self.mongo_col.find_one({"user_id": uid})
                if doc:
                    return doc
            except Exception:
                print(f"[Daily/DB] _get_profile error uid={uid}:")
                traceback.print_exc()
        local = self._local.get(user_id, {})
        return {
            "user_id":         uid,
            "affection_points": local.get("affection", AFFECTION_DEFAULT),
            "last_daily":       local.get("last_daily"),
        }

    async def _grant_daily(self, user_id: int) -> int:
        """Increment affection by AFFECTION_BONUS, record timestamp. Returns new affection."""
        uid       = str(user_id)
        now       = datetime.now(timezone.utc)
        profile   = await self._get_profile(user_id)
        old_aff   = profile.get("affection_points", AFFECTION_DEFAULT)
        new_aff   = min(100, old_aff + AFFECTION_BONUS)

        # Persist to MongoDB
        if self.mongo_col is not None:
            try:
                await self.mongo_col.update_one(
                    {"user_id": uid},
                    {
                        "$set": {
                            "affection_points": new_aff,
                            "last_daily":       now.isoformat(),
                        }
                    },
                    upsert=True,
                )
            except Exception:
                print(f"[Daily/DB] _grant_daily error uid={uid}:")
                traceback.print_exc()

        # Update in-memory fallback
        self._local[user_id] = {"affection": new_aff, "last_daily": now}
        return new_aff

    def _hours_until_next_daily(self, last_daily_raw) -> float | None:
        """Returns remaining hours, or None if cooldown has passed."""
        if last_daily_raw is None:
            return None
        if isinstance(last_daily_raw, str):
            try:
                last = datetime.fromisoformat(last_daily_raw)
            except ValueError:
                return None
        elif isinstance(last_daily_raw, datetime):
            last = last_daily_raw
        else:
            return None

        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)

        elapsed = (datetime.now(timezone.utc) - last).total_seconds() / 3600
        if elapsed >= DAILY_COOLDOWN_HOURS:
            return None
        return DAILY_COOLDOWN_HOURS - elapsed

    # ── Command ────────────────────────────────────────────────────────────────

    @commands.command(name="daily")
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def daily(self, ctx):
        """Claim your daily reward — vote on Top.gg first! 🗳️"""
        user      = ctx.author
        user_id   = user.id
        user_name = user.display_name

        topgg_token = os.getenv("TOPGG_TOKEN")

        # ── 24-hour cooldown check ─────────────────────────────────────────────
        profile     = await self._get_profile(user_id)
        last_daily  = profile.get("last_daily")
        hours_left  = self._hours_until_next_daily(last_daily)

        if hours_left is not None:
            h = int(hours_left)
            m = int((hours_left - h) * 60)
            embed = discord.Embed(
                title="⏳ Matte, matte~!",
                description=(
                    f"Ara ara, {user_name}-kun~ You already claimed your daily reward!\n\n"
                    f"Come back in **{h}h {m}m** and I'll have something special waiting for you~ 🌸"
                ),
                color=0xFFB6C1,
            )
            embed.set_footer(text="Yua loves you~ but patience is also love! ❤️")
            await ctx.reply(embed=embed)
            return

        # ── Top.gg vote check ──────────────────────────────────────────────────
        if topgg_token:
            bot_id = self.bot.user.id
            async with aiohttp.ClientSession() as session:
                has_voted = await _check_topgg_vote(session, topgg_token, bot_id, user_id)

            if not has_voted:
                vote_url = f"https://top.gg/bot/{bot_id}/vote"
                embed = discord.Embed(
                    title="💌 Vote for Yua first, Senpai~!",
                    description=(
                        f"Mou~ {user_name}-senpai, you haven't voted for me yet today! 😳\n\n"
                        f"Click the button below to vote on **Top.gg** — "
                        f"it's free and only takes 2 seconds!\n\n"
                        f"Once you vote, come back and claim your daily reward. "
                        f"I'll be waiting~ 🌸❤️"
                    ),
                    color=0xFF69B4,
                )
                embed.add_field(
                    name="🗳️ Vote Link",
                    value=f"[Click here to vote for Yua!]({vote_url})",
                    inline=False,
                )
                embed.set_footer(text="Voting helps Yua grow~ Arigatou, Senpai! ✨")
                await ctx.reply(embed=embed)
                return
        else:
            print("[Daily] TOPGG_TOKEN not set — skipping vote check.")

        # ── Grant reward ───────────────────────────────────────────────────────
        new_aff   = await self._grant_daily(user_id)
        aff_bar   = _affection_bar(new_aff)
        old_aff   = new_aff - AFFECTION_BONUS

        # Determine tier label
        if new_aff <= 25:
            tier_label = "Tsundere Mode 🧊"
        elif new_aff <= 65:
            tier_label = "Warm & Playful 🌸"
        else:
            tier_label = "Ultra Loving ❤️‍🔥"

        # Kiss animation lines
        kiss_lines = [
            "Chu~! 💋",
            "M-mou! T-this is just a reward, okay?! ...Chu~ 💋😳",
            "Ara ara~ Don't make a big deal out of it... *chu* 💋✨",
            "Daisuki, {name}-kun~ Chu~! 💋🌸",
            "*leans closer* ...Chu~! 💋 A-arigatou for always coming back! ❤️",
        ]
        import random
        kiss = random.choice(kiss_lines).replace("{name}", user_name)

        embed = discord.Embed(
            title="🎁 Daily Reward Claimed~! ✨",
            description=(
                f"{kiss}\n\n"
                f"Arigatou for voting, {user_name}-senpai~! "
                f"Your love means everything to Yua! 🌸"
            ),
            color=0xFF1493,
        )
        embed.add_field(
            name="💖 Affection Points",
            value=(
                f"`{old_aff}` → **`{new_aff}`** (+{AFFECTION_BONUS}) ✨\n"
                f"{aff_bar}\n"
                f"*{tier_label}*"
            ),
            inline=False,
        )
        embed.add_field(
            name="⏰ Next Daily",
            value=f"Come back in **24 hours** for another reward~",
            inline=False,
        )
        embed.set_footer(text=f"Yua's affection for {user_name}: {new_aff}/100 💋")
        await ctx.reply(embed=embed)

    @daily.error
    async def daily_error(self, ctx, error):
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.reply(
                f"Matte~ {ctx.author.display_name}! You're clicking too fast! 😳 "
                f"Try again in {error.retry_after:.1f}s~"
            )
        else:
            print(f"[Daily] Unhandled error: {error}")
            traceback.print_exc()


async def setup(bot):
    await bot.add_cog(Daily(bot))
