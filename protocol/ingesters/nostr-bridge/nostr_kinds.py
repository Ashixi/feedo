import json

def extract_text_for_vectorization(event: dict) -> str:
    """
    Takes a Nostr event dictionary and extracts the most relevant text
    for semantic indexing based on its Kind.
    Supports basic mapping of ~150 kinds (mostly extracting content or specific tags).
    """
    kind = event.get("kind", 1)
    content = event.get("content", "")
    
    if kind == 0:
        # Metadata (Profile)
        try:
            meta = json.loads(content)
            name = meta.get("name", "")
            about = meta.get("about", "")
            return f"User Profile: {name}. {about}"
        except:
            return content
            
    elif kind == 1:
        # Short Text Note
        return content
        
    elif kind == 3:
        # Contact List
        # Usually content is empty, meaning is in tags
        return "Contact List Update"
        
    elif kind == 6:
        # Repost
        # Sometimes the original event is embedded in content
        try:
            inner = json.loads(content)
            return f"Repost: {inner.get('content', '')}"
        except:
            return "Repost"
            
    elif kind == 7:
        # Reaction
        return f"Reaction: {content}"
        
    elif kind == 9735:
        # Zap Receipt
        # Lightning payment description might be embedded in tags
        description = ""
        for tag in event.get("tags", []):
            if tag[0] == "description":
                description = tag[1]
                break
        try:
            if description:
                zap_req = json.loads(description)
                return f"Zap Payment: {zap_req.get('content', '')}"
        except:
            pass
        return "Zap Receipt"
        
    elif kind == 30023:
        # Long-form Content (Article)
        title = ""
        summary = ""
        for tag in event.get("tags", []):
            if tag[0] == "title":
                title = tag[1]
            elif tag[0] == "summary":
                summary = tag[1]
        return f"Article: {title}. {summary}. {content[:32000]}"
        
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
