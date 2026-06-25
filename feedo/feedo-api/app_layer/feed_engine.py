class FeedEngine:
    @staticmethod
    def generate_smart_feed(brain, user_vector: list[float], limit: int = 50, source_type: str = "main", user_languages: list[str] | None = None, user_geo: str | None = None, is_premium: bool = False) -> dict:
        if not user_vector:
            return {"relevant": [], "discovery": [], "promoted": []}

        # 1. Fetch raw posts from Core Protocol
        results = brain.semantic_search(user_vector, limit=200, source_type=source_type)
        
        # 2. Fetch promoted posts from Core Protocol
        promoted_results = []
        if not is_premium:
            promoted_results = brain.semantic_search(user_vector, limit=10, item_type="promoted")

        relevant_ids = []
        discovery_ids = []
        promoted_ids = []
        
        rel_target = int(limit * 0.7)
        disc_target = int(limit * 0.3)
        
        # Обробка просуваних постів
        for res in promoted_results:
            post_id = res.get("post_id")
            if post_id:
                similarity = 1.0 - (res.get("distance", 2.0) / 2.0)
                if similarity > 0.5: # Реклама має бути хоча б трохи релевантною
                    promoted_ids.append(post_id)
                if len(promoted_ids) >= 3: # Максимум 3 реклами на запит
                    break

        user_langs = [l.lower() for l in (user_languages or [])]
        for res in results:
            post_id = res.get("post_id")
            if not post_id:
                continue
                
            similarity = 1.0 - (res.get("distance", 2.0) / 2.0)
            lang = (res.get("language") or "").lower()
            geo = (res.get("geo") or "")

            if user_langs:
                if lang in user_langs:
                    lang_w = 1.0
                elif not lang:
                    lang_w = 0.9
                else:
                    lang_w = 0.5
            else:
                lang_w = 1.0

            if user_geo and geo:
                if geo == user_geo:
                    geo_w = 1.2
                elif geo.split("-")[0] == user_geo.split("-")[0]:
                    geo_w = 1.05
                else:
                    geo_w = 0.6
            else:
                geo_w = 1.0

            score = similarity * lang_w * geo_w

            if score > 0.65:
                if len(relevant_ids) < rel_target:
                    relevant_ids.append((post_id, score))
            elif 0.2 < score <= 0.65:
                if len(discovery_ids) < disc_target:
                    discovery_ids.append((post_id, score))
                    
            if len(relevant_ids) >= rel_target and len(discovery_ids) >= disc_target:
                break

        return {"relevant": relevant_ids, "discovery": discovery_ids, "promoted": promoted_ids}
