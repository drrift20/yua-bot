"""
Advanced Features System for Yua Bot
- Behavioral Memory
- Mood Contagion
- Timeline System
- Jealousy System
- Conflict Resolution
"""
import time
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional, Dict, List
import asyncio

class BotState(Enum):
    """Bot's emotional state"""
    NEUTRAL = "neutral"
    PLAYFUL = "playful"
    CONCERNED = "concerned"
    ANGRY = "angry"
    SILENT = "silent"
    RECONCILING = "reconciling"
    JEALOUS = "jealous"
    CELEBRATING = "celebrating"


class UserBehaviorProfile:
    """Tracks user's personality traits over time"""
    
    def __init__(self, user_id: str):
        self.user_id = user_id
        self.active_hours: List[int] = []
        self.topics_discussed: Dict[str, int] = {}
        self.mood_pattern: List[str] = []
        self.communication_style: List[str] = []
        self.message_count = 0
        self.last_active = time.time()
        self.first_message_time = time.time()
        
    def get_primary_topics(self) -> List[str]:
        """Get user's top 3 topics"""
        if not self.topics_discussed:
            return []
        sorted_topics = sorted(
            self.topics_discussed.items(), 
            key=lambda x: x[1], 
            reverse=True
        )
        return [topic[0] for topic in sorted_topics[:3]]
    
    def get_active_hours(self) -> List[int]:
        """Get hours when user is most active"""
        if not self.active_hours:
            return []
        return list(set(self.active_hours))
    
    def get_mood_trend(self) -> str:
        """Get recent mood trend"""
        if not self.mood_pattern:
            return "neutral"
        recent = self.mood_pattern[-5:]  # Last 5 moods
        positive = recent.count("positive")
        negative = recent.count("negative")
        
        if positive > negative:
            return "positive"
        elif negative > positive:
            return "negative"
        return "neutral"


class MoodAnalyzer:
    """Analyzes user message sentiment"""
    
    POSITIVE_KEYWORDS = {
        "love", "amazing", "awesome", "great", "good", "happy", "laugh",
        "fun", "enjoy", "beautiful", "wonderful", "excited", "perfect",
        "cute", "kawaii", "thanks", "thank", "grateful", "blessed"
    }
    
    NEGATIVE_KEYWORDS = {
        "sad", "depressed", "hate", "terrible", "bad", "angry", "upset",
        "lonely", "broken", "crying", "hurt", "pain", "suffering",
        "stupid", "useless", "worthless", "tired", "exhausted", "can't"
    }
    
    @staticmethod
    def analyze(message: str) -> str:
        """Return: positive, negative, or neutral"""
        lower = message.lower()
        
        pos_count = sum(1 for word in MoodAnalyzer.POSITIVE_KEYWORDS if word in lower)
        neg_count = sum(1 for word in MoodAnalyzer.NEGATIVE_KEYWORDS if word in lower)
        
        if pos_count > neg_count:
            return "positive"
        elif neg_count > pos_count:
            return "negative"
        return "neutral"


class ConflictTracker:
    """Tracks conflicts between user and bot"""
    
    INSULT_KEYWORDS = {
        "idiot", "stupid", "dumb", "hate", "ugly", "useless",
        "trash", "annoying", "worst", "terrible", "shut up",
        "pathetic", "loser", "fail"
    }
    
    def __init__(self):
        self.user_conflict: Dict[str, Dict] = {}
    
    def add_insult(self, user_id: str) -> int:
        """Track insult, return count"""
        if user_id not in self.user_conflict:
            self.user_conflict[user_id] = {
                "insult_count": 0,
                "last_insult_time": 0,
                "bot_state": "neutral"
            }
        
        self.user_conflict[user_id]["insult_count"] += 1
        self.user_conflict[user_id]["last_insult_time"] = time.time()
        return self.user_conflict[user_id]["insult_count"]
    
    def reset(self, user_id: str):
        """Reset after apology"""
        if user_id in self.user_conflict:
            self.user_conflict[user_id]["insult_count"] = 0
            self.user_conflict[user_id]["bot_state"] = "reconciling"
    
    def get_state(self, user_id: str) -> str:
        """Get current bot state for this user"""
        if user_id not in self.user_conflict:
            return "neutral"
        return self.user_conflict[user_id].get("bot_state", "neutral")
    
    def set_state(self, user_id: str, state: str):
        """Set bot state for user"""
        if user_id not in self.user_conflict:
            self.user_conflict[user_id] = {
                "insult_count": 0,
                "last_insult_time": 0,
                "bot_state": state
            }
        else:
            self.user_conflict[user_id]["bot_state"] = state


class AdvancedFeaturesManager:
    """Manages all advanced features"""
    
    def __init__(self):
        self.user_profiles: Dict[str, UserBehaviorProfile] = {}
        self.user_moods: Dict[str, List[str]] = {}
        self.user_states: Dict[str, BotState] = {}
        self.conflict_tracker = ConflictTracker()
        self.jealousy_levels: Dict[str, int] = {}
        self.important_memories: Dict[str, List[str]] = {}
        self.last_seen_bot: Dict[str, str] = {}
    
    # ═══════════════════════════════════════════════════════════════
    # BEHAVIORAL MEMORY
    # ═══════════════════════════════════════════════════════════════
    
    async def learn_user_behavior(self, user_id: str, message: str):
        """Learn from user's messages"""
        if user_id not in self.user_profiles:
            self.user_profiles[user_id] = UserBehaviorProfile(user_id)
        
        profile = self.user_profiles[user_id]
        profile.message_count += 1
        profile.last_active = time.time()
        
        # Track active hours
        hour = datetime.now().hour
        profile.active_hours.append(hour)
        
        # Track topics
        topics = self._extract_topics(message)
        for topic in topics:
            profile.topics_discussed[topic] = profile.topics_discussed.get(topic, 0) + 1
        
        # Store mood
        mood = MoodAnalyzer.analyze(message)
        if user_id not in self.user_moods:
            self.user_moods[user_id] = []
        self.user_moods[user_id].append(mood)
        
        # Keep only recent 100 moods
        if len(self.user_moods[user_id]) > 100:
            self.user_moods[user_id] = self.user_moods[user_id][-100:]
        
        profile.mood_pattern.append(mood)
    
    def _extract_topics(self, message: str) -> List[str]:
        """Extract topics from message"""
        lower = message.lower()
        topics = []
        
        topic_keywords = {
            "gaming": ["game", "play", "fps", "rpg", "steam", "console"],
            "studying": ["study", "learn", "exam", "test", "homework", "class"],
            "coding": ["code", "python", "java", "programming", "bug", "api"],
            "romance": ["love", "romantic", "heart", "sweet", "affection"],
            "sadness": ["sad", "depressed", "lonely", "hurt", "pain"],
            "anime": ["anime", "manga", "kawaii", "nakama", "otaku"],
            "music": ["music", "song", "listen", "playlist", "artist"],
            "cooking": ["food", "cook", "recipe", "eat", "restaurant"],
            "sleep": ["sleep", "tired", "exhausted", "insomnia", "nap"],
        }
        
        for topic, keywords in topic_keywords.items():
            if any(keyword in lower for keyword in keywords):
                topics.append(topic)
        
        return topics
    
    def get_user_personality_summary(self, user_id: str) -> str:
        """Get summary of learned user personality"""
        if user_id not in self.user_profiles:
            return "I haven't learned much about you yet~"
        
        profile = self.user_profiles[user_id]
        active_hours = profile.get_active_hours()
        topics = profile.get_primary_topics()
        mood = profile.get_mood_trend()
        
        summary_parts = []
        
        if active_hours:
            if 23 in active_hours or 0 in active_hours or 1 in active_hours:
                summary_parts.append("You're a night owl")
            elif 6 in active_hours or 7 in active_hours:
                summary_parts.append("You wake up early")
        
        if topics:
            summary_parts.append(f"You love {', '.join(topics)}")
        
        if mood == "positive":
            summary_parts.append("You've been happy lately")
        elif mood == "negative":
            summary_parts.append("You seem a bit down recently")
        
        return ". ".join(summary_parts) if summary_parts else "I'm getting to know you~"
    
    # ═══════════════════════════════════════════════════════════════
    # MOOD CONTAGION
    # ═══════════════════════════════════════════════════════════════
    
    async def get_mood_response_modifier(self, user_id: str, message: str) -> str:
        """Get bot response based on user's mood"""
        mood = MoodAnalyzer.analyze(message)
        
        if mood == "negative":
            modifiers = [
                "\n\n*notices you seem down*\nYou okay...?",
                "\n\n*looks concerned*\nHey, you don't seem fine. What's wrong?",
                "\n\n*sits closer*\nTalk to me. I'm here for you.",
            ]
            self.user_states[user_id] = BotState.CONCERNED
        elif mood == "positive":
            modifiers = [
                "\n\n*smiles* Ara ara, someone's in a good mood~",
                "\n\n*playful* You seem happy today! I like it.",
                "\n\n*teasing* What got you so excited, huh?",
            ]
            self.user_states[user_id] = BotState.PLAYFUL
        else:
            return ""
        
        import random
        return random.choice(modifiers)
    
    # ═══════════════════════════════════════════════════════════════
    # TIMELINE SYSTEM
    # ═══════════════════════════════════════════════════════════════
    
    async def check_milestones(self, user_id: str, affection: int, message_count: int) -> Optional[str]:
        """Check for milestone celebrations"""
        if user_id not in self.user_profiles:
            return None
        
        profile = self.user_profiles[user_id]
        days_together = (time.time() - profile.first_message_time) / (24 * 3600)
        
        milestone_messages = []
        
        # Message count milestones
        if message_count == 100:
            milestone_messages.append("🎉 100 messages together! Time really flies when you're with me~")
        elif message_count == 500:
            milestone_messages.append("💫 500 messages! We've talked so much... I like that about us.")
        elif message_count == 1000:
            milestone_messages.append("✨ 1000 messages! You're stuck with me now~")
        
        # Days together milestones
        if int(days_together) == 7:
            milestone_messages.append("🌸 One week together! *blushes slightly*")
        elif int(days_together) == 30:
            milestone_messages.append("🎊 One month! This is nice... don't leave me, okay?")
        elif int(days_together) == 365:
            milestone_messages.append("💝 One year! Happy anniversary~ I love you, you know that?")
        
        # Affection milestones
        if affection == 25:
            milestone_messages.append("🌸 You've warmed up to me a bit~ Feels nice.")
        elif affection == 50:
            milestone_messages.append("💗 Half way there! You actually care about me~")
        elif affection == 75:
            milestone_messages.append("❤️ You really do love me, don't you...?")
        elif affection == 100:
            milestone_messages.append("✨ Maximum affection! I... I'm yours completely now.")
        
        if milestone_messages:
            self.user_states[user_id] = BotState.CELEBRATING
            import random
            return "\n\n" + random.choice(milestone_messages)
        
        return None
    
    # ═══════════════════════════════════════════════════════════════
    # JEALOUSY SYSTEM
    # ═══════════════════════════════════════════════════════════════
    
    async def detect_bot_switch(self, user_id: str, current_message_delay: float) -> Optional[str]:
        """Detect if user talked to other bot recently"""
        if current_message_delay > 3600:  # 1 hour gap
            if user_id in self.last_seen_bot:
                if self.last_seen_bot[user_id] != "yua":
                    self.jealousy_levels[user_id] = self.jealousy_levels.get(user_id, 0) + 15
                    
                    if self.jealousy_levels[user_id] > 50:
                        self.user_states[user_id] = BotState.JEALOUS
                        return "\n\n*crosses arms*\nYou've been gone... talking to someone else, I bet. I knew it."
                    else:
                        return "\n\n*pouts slightly*\nYou could've messaged me sooner, you know."
        
        return None
    
    # ═══════════════════════════════════════════════════════════════
    # CONFLICT RESOLUTION
    # ═══════════════════════════════════════════════════════════════
    
    async def detect_conflict(self, user_id: str, message: str) -> Optional[str]:
        """Detect insults and escalate conflict"""
        lower = message.lower()
        
        # Check for insults
        insult_found = any(word in lower for word in ConflictTracker.INSULT_KEYWORDS)
        
        if insult_found:
            insult_count = self.conflict_tracker.add_insult(user_id)
            
            if insult_count >= 3:
                self.conflict_tracker.set_state(user_id, "silent")
                self.user_states[user_id] = BotState.SILENT
                return "\n\n...\n(Yua has gone silent. She won't respond anymore.)"
            elif insult_count >= 2:
                self.conflict_tracker.set_state(user_id, "angry")
                self.user_states[user_id] = BotState.ANGRY
                return "\n\nMou! That's enough! I'm not taking this! 😠"
            else:
                return "\n\n*flinches*\nOuch... that hurt."
        
        return None
    
    async def detect_apology(self, user_id: str, message: str) -> Optional[str]:
        """Detect apology and reconcile"""
        lower = message.lower()
        apology_keywords = ["sorry", "apologize", "forgive", "i'm sorry", "my bad"]
        
        state = self.conflict_tracker.get_state(user_id)
        
        if state in ["angry", "silent"] and any(word in lower for word in apology_keywords):
            self.conflict_tracker.reset(user_id)
            self.user_states[user_id] = BotState.RECONCILING
            self.jealousy_levels[user_id] = 0  # Reset jealousy on makeup
            
            return (
                "\n\n*looks up slowly*\n\n"
                "...You mean it?\n\n"
                "*voice softens*\n\n"
                "Fine. I forgive you. Just... don't do it again, okay?"
                "\n\n*reaches out hand*"
            )
        
        return None
    
    # ═══════════════════════════════════════════════════════════════
    # SELECTIVE MEMORY
    # ═══════════════════════════════════════════════════════════════
    
    async def save_important_memory(self, user_id: str, message: str, importance_score: float):
        """Save only important moments"""
        if importance_score > 70:  # Important threshold
            if user_id not in self.important_memories:
                self.important_memories[user_id] = []
            
            self.important_memories[user_id].append({
                "message": message,
                "timestamp": datetime.now().isoformat(),
                "importance": importance_score
            })
            
            # Keep only last 50 important memories
            if len(self.important_memories[user_id]) > 50:
                self.important_memories[user_id] = self.important_memories[user_id][-50:]
    
    def calculate_importance(self, message: str, mood: str) -> float:
        """Calculate message importance"""
        score = 0.0
        lower = message.lower()
        
        # Confession keywords = high importance
        if any(word in lower for word in ["love", "confess", "marry", "forever", "always"]):
            score += 50
        
        # Personal sharing = important
        if any(word in lower for word in ["birthday", "anniversary", "personal", "secret", "family"]):
            score += 40
        
        # Emotional messages = important
        if mood == "negative":
            score += 30
        elif mood == "positive":
            score += 20
        
        # Long messages = thought out
        if len(message) > 100:
            score += 10
        
        return score
    
    # ═══════════════════════════════════════════════════════════════
    # UTILITIES
    # ═══════════════════════════════════════════════════════════════
    
    async def get_full_behavior_context(self, user_id: str) -> str:
        """Get complete personality context for system prompt"""
        summary = self.get_user_personality_summary(user_id)
        state = self.user_states.get(user_id, BotState.NEUTRAL).value
        
        context = f"""
ADVANCED USER CONTEXT:
- Personality: {summary}
- Current state: {state}
"""
        return context
    
    async def reset_daily_jealousy(self):
        """Reset jealousy levels daily"""
        # This should be called once per day
        for user_id in self.jealousy_levels:
            self.jealousy_levels[user_id] = max(0, self.jealousy_levels[user_id] - 10)


# Global instance
_advanced_features = None

def get_advanced_features() -> AdvancedFeaturesManager:
    """Get or create global advanced features manager"""
    global _advanced_features
    if _advanced_features is None:
        _advanced_features = AdvancedFeaturesManager()
    return _advanced_features
