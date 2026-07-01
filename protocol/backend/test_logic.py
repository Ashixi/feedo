def test_interleaving():
    sorted_hashes = [
        "A1", "A2", "B1", "B2", "A3", "C1", "A4", "A5", "A6"
    ]
    author_map = {
        "A1": "Author_A", "A2": "Author_A", "A3": "Author_A", "A4": "Author_A", "A5": "Author_A", "A6": "Author_A",
        "B1": "Author_B", "B2": "Author_B",
        "C1": "Author_C"
    }
    
    fetch_limit = 100
    final_feed = []
    recent_authors = []
    pending = list(sorted_hashes)
    
    while pending and len(final_feed) < fetch_limit:
        found_index = -1
        for i, hid in enumerate(pending):
            author = author_map.get(hid)
            if not author or author not in recent_authors:
                found_index = i
                break
                
        if found_index == -1:
            found_index = 0
            
        hid = pending.pop(found_index)
        final_feed.append(hid)
        
        author = author_map.get(hid)
        if author:
            recent_authors.append(author)
            if len(recent_authors) > 2:
                recent_authors.pop(0)

    print(f"Final Feed: {final_feed}")
    for hid in final_feed:
        print(author_map[hid])

test_interleaving()
