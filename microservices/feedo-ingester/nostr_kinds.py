import json

def extract_data_for_vectorization(event: dict) -> dict | None:
    """
    Takes a Nostr event dictionary and extracts the most relevant text
    for semantic indexing based on its Kind, and optionally a target_hash for reactions.
    Returns a dict with 'text' and 'target_hash', or None if it should be dropped.
    """
    kind = event.get("kind", 1)
    content = event.get("content", "")
    
    # Helper to find target 'e' tag
    def get_e_tag():
        for tag in event.get("tags", []):
            if tag[0] == "e":
                return tag[1]
        return None

    if kind == 0:
        # Metadata (Profile)
        try:
            meta = json.loads(content)
            name = meta.get("name", "")
            about = meta.get("about", "")
            return {"text": f"User Profile: {name}. {about}", "target_hash": None}
        except:
            return {"text": content, "target_hash": None}
            
    elif kind == 1:
        # Short Text Note
        # If it has an 'e' tag, it's a reply. We drop replies!
        if get_e_tag():
            return None
        return {"text": content, "target_hash": None}
        
    elif kind == 3:
        return {"text": "Contact List Update", "target_hash": None}
        
    elif kind == 6:
        # Repost
        target = get_e_tag()
        try:
            inner = json.loads(content)
            return {"text": f"Repost: {inner.get('content', '')}", "target_hash": target}
        except:
            return {"text": "Repost", "target_hash": target}
            
    elif kind == 7:
        # Reaction
        return {"text": f"Reaction: {content}", "target_hash": get_e_tag()}
        
    elif kind == 9735:
        # Zap Receipt
        description = ""
        for tag in event.get("tags", []):
            if tag[0] == "description":
                description = tag[1]
                break
        target_hash = get_e_tag()
        try:
            if description:
                zap_req = json.loads(description)
                return {"text": f"Zap Payment: {zap_req.get('content', '')}", "target_hash": target_hash}
        except:
            pass
        return {"text": "Zap Receipt", "target_hash": target_hash}
        
    elif kind == 30023:
        # Long-form Content (Article)
        title = ""
        summary = ""
        for tag in event.get("tags", []):
            if tag[0] == "title":
                title = tag[1]
            elif tag[0] == "summary":
                summary = tag[1]
        return {"text": f"Article: {title}. {summary}. {content[:32000]}", "target_hash": None}
        
    elif kind in (40, 41, 42):
        # Public Chat Channel (Creation, Metadata, Message)
        try:
            meta = json.loads(content) if kind != 42 else {}
            name = meta.get("name", "")
            about = meta.get("about", "")
            return f"Channel {name}: {about}" if kind != 42 else f"Channel Msg: {content}"
        except:
            return f"Channel Msg: {content}"
            
    elif kind == 1063:
        # File Metadata
        desc = ""
        for tag in event.get("tags", []):
            if tag[0] == "x": desc = tag[1]
        return f"File Metadata: {desc} {content}"
        
    elif kind == 1311:
        # Live Chat Message
        return f"Live Chat: {content}"
        
    elif kind == 1984:
        # Reporting
        return f"Report: {content}"
        
    elif kind == 9802:
        # Highlights
        context = ""
        for tag in event.get("tags", []):
            if tag[0] == "context": context = tag[1]
        return f"Highlight: {content}. Context: {context}"
        
    elif kind in (10000, 10001, 10002, 30000, 30001):
        # Mute list, Pin list, Relay list, Categorized People/Bookmark list
        return f"List Update: {content}"
        
    elif kind == 30008:
        # Profile Badges
        return f"Profile Badges: {content}"
        
    elif kind == 30009:
        # Badge Definition
        name = ""
        desc = ""
        for tag in event.get("tags", []):
            if tag[0] == "name": name = tag[1]
            if tag[0] == "description": desc = tag[1]
        return f"Badge: {name}. {desc}"
        
    elif kind == 30311:
        # Live Event
        title = ""
        summary = ""
        for tag in event.get("tags", []):
            if tag[0] == "title": title = tag[1]
            if tag[0] == "summary": summary = tag[1]
        return f"Live Event: {title}. {summary}"
        
    elif kind in (31922, 31923):
        # Calendar Event
        name = ""
        desc = ""
        for tag in event.get("tags", []):
            if tag[0] == "name": name = tag[1]
            if tag[0] == "description": desc = tag[1]
        return f"Calendar Event: {name}. {desc}"
        
    elif kind == 31990:
        # Handler recommendation
        return f"App Handler: {content}"
        
    elif kind == 34550:
        # Community Definition
        desc = ""
        for tag in event.get("tags", []):
            if tag[0] == "description": desc = tag[1]
        return f"Community: {desc}"
        
    # Fallback for the other ~140 kinds
    # If there is content, we just return it, maybe prefixed by kind
    if content:
        return f"Kind {kind}: {content}"
        
    return ""
