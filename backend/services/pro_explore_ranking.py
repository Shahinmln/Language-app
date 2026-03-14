from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional


class ProExploreRanking:
    """
    Personalized ranking of stories based on SRS urgency + engagement.

    Expects a Supabase client compatible with supabase-py v2
    (table(...).select(...).eq(...).execute()).
    """

    def __init__(self, supabase_client: Any):
        self.supabase = supabase_client
        self.weights = {"linguistic": 0.65, "marketing": 0.35}

        self.word_score_caps = {
            "srs_urgency": 25,
            "want_to_learn": 20,
            "reinforcement": 10,
            "context_variety": 5,
            "total": 60,
        }
        self.content_score_caps = {
            "level_match": 15,
            "topic_match": 10,
            "social_proof": 10,
            "content_quality": 5,
            "total": 40,
        }

    async def calculate_story_score(self, user_id: str, story_id: str) -> Dict[str, Any]:
        """Calculate personalized score for a single story."""
        import anyio

        async def run_sync(fn, *args, **kwargs):
            return await anyio.to_thread.run_sync(fn, *args, **kwargs)

        user_profile, user_words, user_interests, story, story_words = await anyio.gather(
            run_sync(self._get_user_profile, user_id),
            run_sync(self._get_user_words, user_id),
            run_sync(self._get_user_interests, user_id),
            run_sync(self._get_story_details, story_id),
            run_sync(self._get_story_word_index, story_id),
        )

        linguistic_score = self._calc_linguistic(user_words, story_words, user_profile)
        marketing_score = self._calc_marketing(story, user_interests, user_profile)

        final_score = (linguistic_score * self.weights["linguistic"] +
                       marketing_score * self.weights["marketing"])

        return {
            "total_score": round(final_score, 2),
            "linguistic_score": round(linguistic_score, 2),
            "marketing_score": round(marketing_score, 2),
            "word_match_percentage": self._calc_match_pct(user_words, story_words),
            "matched_want_to_learn": self._get_matched(user_words, story_words, "want_to_learn")[:5],
            "matched_review_due": self._get_matched(user_words, story_words, "reviewing", due=True)[:5],
            "recommendation_reason": self._gen_reason(user_words, story_words, linguistic_score),
            "badge": self._get_badge(final_score),
        }

    # ----- Scoring internals -------------------------------------------------

    def _calc_linguistic(
        self,
        user_words: List[Dict[str, Any]],
        story_words: List[Dict[str, Any]],
        user_profile: Optional[Dict[str, Any]],
    ) -> float:
        """Max 60 points - Based on Ebbinghaus Forgetting Curve."""
        score = 0.0
        today = datetime.now().date()
        story_word_set = {sw.get("word", "").lower() for sw in story_words}
        matched = [w for w in user_words if w.get("word", "").lower() in story_word_set]

        # SRS Urgency (Max 25 pts)
        srs_score = 0.0
        for w in matched:
            if w.get("status") == "reviewing" and w.get("next_review_date"):
                try:
                    next_rev = datetime.fromisoformat(str(w["next_review_date"])).date()
                except ValueError:
                    continue
                days_overdue = (today - next_rev).days
                if days_overdue >= 7:
                    srs_score += 10
                elif days_overdue >= 4:
                    srs_score += 8
                elif days_overdue >= 1:
                    srs_score += 5
                elif days_overdue == 0:
                    srs_score += 3
        score += min(srs_score, self.word_score_caps["srs_urgency"])

        # Want-to-Learn (Max 20 pts)
        wtl_score = sum(3 for w in matched if w.get("status") == "want_to_learn")
        score += min(wtl_score, self.word_score_caps["want_to_learn"])

        # Reinforcement (Max 10 pts)
        rein_score = sum(
            2 for w in matched if w.get("status") == "mastered" and (w.get("times_encountered") or 0) < 3
        )
        score += min(rein_score, self.word_score_caps["reinforcement"])

        # Level Match (i+1 Theory) - Max 15 pts
        familiar_ratio = self._calc_familiar_ratio(story_words, user_words)
        if 0.70 <= familiar_ratio <= 0.80:
            score += 15
        elif 0.80 < familiar_ratio <= 0.90:
            score += 12
        elif 0.60 <= familiar_ratio < 0.70:
            score += 10
        elif familiar_ratio < 0.50:
            score -= 5

        return min(score, float(self.word_score_caps["total"]))

    def _calc_marketing(
        self,
        story: Dict[str, Any],
        user_interests: List[Dict[str, Any]],
        user_profile: Optional[Dict[str, Any]],
    ) -> float:
        """Max 40 points - Based on engagement optimization."""
        score = 0.0

        # Topic Match (Max 10 pts)
        topic = (story.get("topic") or "").lower()
        for interest in user_interests:
            if (interest.get("topic") or "").lower() == topic:
                score += (interest.get("interest_level") or 0) * 2
                break

        # Social Proof (Max 10 pts)
        plays = story.get("plays_count") or 0
        if plays >= 1000:
            score += 5
        elif plays >= 500:
            score += 3

        completion_rate = story.get("completion_rate") or 0.0
        if completion_rate >= 0.75:
            score += 3

        # Quality (Max 5 pts)
        duration_min = story.get("duration_minutes") or 0
        if 8 <= duration_min <= 12:
            score += 5
        elif 12 < duration_min <= 20:
            score += 3

        return min(score, float(self.content_score_caps["total"]))

    def _get_badge(self, score: float) -> str:
        if score >= 90:
            return "🏆 Mükemmel Uyum"
        if score >= 80:
            return "✨ Sana Özel"
        if score >= 60:
            return "👍 Önerilen"
        return ""

    def _gen_reason(
        self,
        user_words: List[Dict[str, Any]],
        story_words: List[Dict[str, Any]],
        ling_score: float,
    ) -> str:
        reasons: List[str] = []
        due = self._get_matched(user_words, story_words, "reviewing", due=True)
        wtl = self._get_matched(user_words, story_words, "want_to_learn")
        if len(due) >= 2:
            reasons.append(f"🔄 {len(due)} acil tekrar")
        if len(wtl) >= 2:
            reasons.append(f"📚 {len(wtl)} öğrenmek istediğin")
        if ling_score >= 40:
            reasons.append("✨ Seviyene uygun")
        return " • ".join(reasons[:2]) if reasons else "İlgi alanlarına uygun"

    # ----- Data access helpers (sync, wrapped in threads above) --------------

    def _get_user_profile(self, user_id: str) -> Optional[Dict[str, Any]]:
        res = self.supabase.table("profiles").select("*").eq("id", user_id).limit(1).execute()
        return res.data[0] if res.data else None

    def _get_user_words(self, user_id: str) -> List[Dict[str, Any]]:
        res = (
            self.supabase.table("user_words")
            .select("*")
            .eq("user_id", user_id)
            .order("updated_at", desc=True)
            .limit(2000)
            .execute()
        )
        return res.data or []

    def _get_user_interests(self, user_id: str) -> List[Dict[str, Any]]:
        res = (
            self.supabase.table("user_interests")
            .select("*")
            .eq("user_id", user_id)
            .order("interest_level", desc=True)
            .limit(50)
            .execute()
        )
        return res.data or []

    def _get_story_details(self, story_id: str) -> Dict[str, Any]:
        res = self.supabase.table("stories").select("*").eq("id", story_id).limit(1).execute()
        if not res.data:
            return {}
        return res.data[0]

    def _get_story_word_index(self, story_id: str) -> List[Dict[str, Any]]:
        story = self._get_story_details(story_id)
        vocab = story.get("vocabulary") or []
        if isinstance(vocab, list):
            return vocab
        return []

    # ----- Matching utilities ------------------------------------------------

    def _calc_familiar_ratio(
        self, story_words: List[Dict[str, Any]], user_words: List[Dict[str, Any]]
    ) -> float:
        if not story_words:
            return 1.0

        user_known = {
            w.get("word", "").lower() for w in user_words if w.get("status") in ("learning", "reviewing", "mastered")
        }
        total = len(story_words)
        familiar = sum(1 for sw in story_words if sw.get("word", "").lower() in user_known)
        return familiar / total if total else 1.0

    def _calc_match_pct(
        self, user_words: List[Dict[str, Any]], story_words: List[Dict[str, Any]]
    ) -> float:
        if not story_words or not user_words:
            return 0.0
        story_set = {sw.get("word", "").lower() for sw in story_words}
        user_set = {uw.get("word", "").lower() for uw in user_words}
        if not story_set:
            return 0.0
        matched = story_set & user_set
        return round(len(matched) * 100.0 / len(story_set), 2)

    def _get_matched(
        self,
        user_words: List[Dict[str, Any]],
        story_words: List[Dict[str, Any]],
        status: str,
        due: bool = False,
    ) -> List[Dict[str, Any]]:
        today = datetime.now().date()
        story_set = {sw.get("word", "").lower() for sw in story_words}
        out: List[Dict[str, Any]] = []
        for w in user_words:
            if w.get("status") != status:
                continue
            if w.get("word", "").lower() not in story_set:
                continue
            if due:
                next_date_raw = w.get("next_review_date")
                if not next_date_raw:
                    continue
                try:
                    next_date = datetime.fromisoformat(str(next_date_raw)).date()
                except ValueError:
                    continue
                if next_date > today:
                    continue
            out.append(w)
        return out

