import os
import re
import json
import asyncio
import aiohttp
import feedparser

# --- НАЛАШТУВАННЯ AZURE OPENAI ---
AZURE_API_KEY = os.getenv("API_KEY", "твій_ключ")
AZURE_ENDPOINT = os.getenv("ENDPOINT", "твій_ендпоінт")
MAX_WORKERS = 15
POSTS_TO_ANALYZE = 10
MAX_FEEDS_TO_PROCESS = 50 

# Використовуємо raw посилання для отримання чистого Markdown
PUBLIC_RSS_INDEX_URL = "https://raw.githubusercontent.com/plenaryapp/awesome-rss-feeds/master/README.md"

# ==========================================
# --- СЛОВНИКИ КЛАСИФІКАЦІЇ (ENUMS) ---
# ==========================================

CATEGORIES = [
    # Tech & Software
    "Artificial Intelligence", "Machine Learning", "Software Engineering", "Web Development", 
    "Frontend", "Backend", "Mobile Development", "Cybersecurity", "Blockchain", "Web3", 
    "Data Science", "DevOps", "Cloud Computing", "Hardware", "Gadgets", "Consumer Electronics",
    "Open Source", "SaaS", "Indie Hacking", "Game Development", "UI/UX Design", "IT Infrastructure",
    "Robotics", "IoT", "Networking",
    # News & Politics
    "World News", "Local News", "Politics", "Geopolitics", "Investigative Journalism", 
    "Law & Justice", "Human Rights", "Public Policy", "Military & Defense",
    # Business, Finance & Economics
    "Economics", "Macroeconomics", "Venture Capital", "Startups", "Personal Finance", 
    "Markets & Stocks", "Real Estate", "E-commerce", "Marketing", "SEO", "Management", 
    "Leadership", "Cryptocurrency", "DeFi", "Entrepreneurship",
    # Science & Education
    "Space & Astronomy", "Biology", "Medicine", "Healthcare", "Physics", "Chemistry",
    "Climate & Environment", "Psychology", "Sociology", "History", "Education", "Anthropology", 
    "Mathematics", "Neuroscience", "Linguistics",
    # Lifestyle & Culture
    "Travel", "Food & Drink", "Cooking", "Health & Fitness", "Mental Health", "Fashion", 
    "Productivity", "Relationships", "Parenting", "Religion & Spirituality", "Philosophy",
    "Minimalism", "Sustainable Living", "Personal Growth",
    # Entertainment, Arts & Hobbies
    "Gaming", "Movies & TV", "Music", "Pop Culture", "Anime & Manga", "Board Games", 
    "Photography", "Automotive", "DIY & Crafts", "Literature", "Art & Design", "Sports",
    "Comedy", "True Crime", "Podcasting", "Theater", "Architecture",
    # Industry Specific
    "Agriculture", "Energy", "Aviation", "Maritime", "Logistics", "Retail", "Manufacturing", "Other"
]

TONE_AND_STYLE = [
    "Journalistic", "Objective", "Academic", "Casual", "Clickbait", "Corporate", "Opinionated", 
    "Humorous", "Satirical", "Technical", "Analytical", "Sensationalist", "Conversational", 
    "Formal", "Dry", "Emotional", "Inspiring", "Critical", "Neutral", "Aggressive", 
    "Philosophical", "Educational", "Instructional", "Storytelling", "Urgent", "Sarcastic", 
    "Investigative", "Provocative", "Community-driven"
]

CONTENT_FORMATS = [
    "News Report", "Analysis", "Long-form Read", "Tutorial/How-To", "Review", "Op-Ed", 
    "Interview", "Press Release", "Case Study", "Research Paper", "Listicle", "Q&A", "Essay", 
    "Digest/Newsletter", "Personal Blog", "Financial Report", "Live Coverage", "Satire", 
    "Curated Links", "Release Notes", "Job Postings", "Event Announcements", "Data Journalism",
    "Multimedia/Video", "Podcast Show Notes"
]

GEO_FOCUS = [
    "Global", "North America", "USA", "Canada", "Europe", "Ukraine", "Eastern Europe", "UK", 
    "Germany", "France", "Asia", "China", "Japan", "India", "South Korea", "Latin America", 
    "Brazil", "Middle East", "Israel", "Africa", "Australia & Oceania", "CIS", "Local/Municipal",
    "Unknown/Not Applicable"
]

# ==========================================
# --- ШАБЛОН ПРОМПТА (ENGLISH) ---
# ==========================================

SYSTEM_PROMPT_TEMPLATE = """
You are an expert data engineer and media analyst. Your task is to analyze a collection of recent post titles and summaries from an RSS feed, and build a detailed source profile.

CRITICAL INSTRUCTIONS:
1. You MUST select values ONLY from the provided ENUMS lists. Do not invent any new categories, tones, or formats.
2. If there is no perfect match, choose the closest available option from the lists.
3. The 'language' field is MANDATORY. You must determine the primary language of the text and return its standard ISO 639-1 code (e.g., 'uk' for Ukrainian, 'en' for English, 'es' for Spanish).
4. For 'categories', you can select up to 3 values from the list to accurately represent the source.

ALLOWED ENUMS:
- categories: {categories}
- tone_and_style: {tones}
- geo_focus: {geos}
- content_format: {formats}

Your output MUST be a valid, raw JSON object (do not wrap it in Markdown like ```json) with the following exact schema:
{{
    "source_summary": "A short, 1-2 sentence summary of what this feed is about.",
    "language": "<ISO 639-1 code language>",
    "categories": ["<Option 1>", "<Option 2>", "<Option 3>"], // Choose 1 to 3 from the 'categories' enum
    "topics": ["tag1", "tag2", "tag3", "tag4", "tag5"], // Up to 5 highly specific lowercase keywords derived from the text (you can invent these based on context, e.g., 'reactjs', 'war', 'tesla')
    "target_audience": "Who is this content for? (1-3 words, e.g., 'Software Developers', 'General Public', 'Investors')",
    "tone_and_style": "<ONE 'tone_and_style' enum from the value>",
    "technical_complexity": <Integer 1 10 from to>, // 1 = simple daily news/gossip, 10 = advanced scientific/programming research
    "geo_focus": "<ONE 'geo_focus' enum from the value>",
    "content_format": "<ONE 'content_format' enum from the value>"
}}
"""

SYSTEM_PROMPT = SYSTEM_PROMPT_TEMPLATE.format(
    categories=json.dumps(CATEGORIES, ensure_ascii=False),
    tones=json.dumps(TONE_AND_STYLE, ensure_ascii=False),
    geos=json.dumps(GEO_FOCUS, ensure_ascii=False),
    formats=json.dumps(CONTENT_FORMATS, ensure_ascii=False)
)

# ==========================================
# --- ЛОГІКА СКРИПТА ---
# ==========================================

async def fetch_public_rss_index(session: aiohttp.ClientSession) -> list:
    print(f"📥 Fetching public RSS index from {PUBLIC_RSS_INDEX_URL}...")
    try:
        async with session.get(PUBLIC_RSS_INDEX_URL, timeout=20) as response:
            text = await response.text()
            
            # Шукаємо тільки посилання на OPML-файли
            opml_urls = re.findall(r'\[[^\]]+\]\((https?://[^\)]+\.opml)\)', text)
            opml_urls = list(set(opml_urls))
            
            print(f"📂 Found {len(opml_urls)} OPML lists. Extracting actual RSS feeds...")
            
            all_rss_urls = []
            # Беремо перші кілька OPML файлів (щоб не качати тисячі лінків за раз)
            # Можеш змінити [:5] на більшу кількість, якщо треба більше джерел
            for opml_url in opml_urls[:5]: 
                try:
                    async with session.get(opml_url, timeout=10) as opml_resp:
                        opml_text = await opml_resp.text()
                        # Витягуємо справжні RSS-лінки з атрибута xmlUrl
                        rss_links = re.findall(r'xmlUrl="([^"]+)"', opml_text)
                        all_rss_urls.extend(rss_links)
                except Exception as e:
                    print(f"⚠️ Failed to parse OPML {opml_url}: {e}")
            
            # Відбираємо унікальні і обрізаємо до ліміту
            unique_rss = list(set(all_rss_urls))[:MAX_FEEDS_TO_PROCESS]
            
            print(f"✅ Extracted {len(unique_rss)} actual RSS feeds to process.")
            return unique_rss
            
    except Exception as e:
        print(f"❌ Error fetching index: {e}")
        return []

async def fetch_rss_content(session: aiohttp.ClientSession, url: str) -> str:
    try:
        async with session.get(url, timeout=10) as response:
            content = await response.text()
            feed = feedparser.parse(content)
            
            if not feed.entries:
                return ""
            
            aggregated_text = f"URL: {url}\nFeed Title: {feed.feed.get('title', 'Unknown')}\n\n"
            for entry in feed.entries[:POSTS_TO_ANALYZE]:
                aggregated_text += f"Headline: {entry.get('title', '')}\n"
                summary = entry.get('summary', '')[:300] 
                summary = re.sub(r'<[^>]+>', '', summary)
                aggregated_text += f"Snippet: {summary}\n---\n"
                
            return aggregated_text
    except Exception:
        return ""

async def analyze_source(session: aiohttp.ClientSession, url: str, text_content: str) -> dict:
    if not text_content:
        return {"url": url, "error": "No content or connection timeout"}

    headers = {"Content-Type": "application/json", "api-key": AZURE_API_KEY}
    
    payload = {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Classify the following RSS feed content:\n\n{text_content}"}
        ],
        "temperature": 0.1, 
        "max_tokens": 800,
        "response_format": { "type": "json_object" }
    }

    try:
        async with session.post(AZURE_ENDPOINT, headers=headers, json=payload, timeout=20) as response:
            if response.status != 200:
                return {"url": url, "error": f"API Error {response.status}"}
            
            result = await response.json()
            llm_reply = result['choices'][0]['message']['content']
            profile = json.loads(llm_reply)
            profile["url"] = url 
            return profile
            
    except Exception as e:
        return {"url": url, "error": str(e)}

async def process_single_source(session: aiohttp.ClientSession, semaphore: asyncio.Semaphore, url: str):
    async with semaphore:
        content = await fetch_rss_content(session, url)
        if content:
            print(f"🧠 Analyzing: {url}")
            return await analyze_source(session, url, content)
        else:
            print(f"⏭️ Skipping (unreachable/empty): {url}")
            return None

async def main():
    if not AZURE_API_KEY or "твій_ключ" in AZURE_API_KEY:
        print("⚠️ Missing AZURE_API_KEY")
        return

    semaphore = asyncio.Semaphore(MAX_WORKERS)
    
    async with aiohttp.ClientSession() as session:
        rss_sources = await fetch_public_rss_index(session)
        if not rss_sources:
            return

        tasks = [process_single_source(session, semaphore, url) for url in rss_sources]
        results = await asyncio.gather(*tasks)

    valid_results = [r for r in results if r and "error" not in r]

    with open("analyzed_sources.json", "w", encoding="utf-8") as f:
        json.dump(valid_results, f, ensure_ascii=False, indent=4)
        
    print(f"\n🎉 Done! Successfully profiled {len(valid_results)} sources.")

if __name__ == "__main__":
    asyncio.run(main())