import re
import sys

def clean_file(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # 1. Remove unnecessary comments like // --- ... ---
    content = re.sub(r'//\s*---\s*.*\s*---\s*\n', '', content)
    
    # 2. Remove emojis and clean up println! messages.
    # We will find all println! macros and process their literal strings.
    # A simple regex to catch println!("...")
    
    def clean_println(match):
        # The whole println macro string
        full = match.group(0)
        # We want to remove common emojis
        # Emoticons range: [\U00010000-\U0010ffff] covers most emojis in surrogate pairs conceptually, 
        # but in python 3 we can just use the emoji package or regex for typical unicode ranges.
        # Let's just remove any character that is not ASCII or Cyrillic or basic punctuation inside quotes.
        # Actually, let's just strip known emojis: 🚀, 🔧, ✅, 📝, 🗳️, ⚠️, 🌍, 📡, 🔌, 🗃️, 🔑, 🔐, 🌐, 📣, 💾, ❌, 🧠, 🔍, 🎉, 🧹, 🔗, 🗄️, 🔄, ⏳, ➡️, 📥, 📤
        emojis = ['🚀', '🔧', '✅', '📝', '🗳️', '⚠️', '🌍', '📡', '🔌', '🗃️', '🔑', '🔐', '🌐', '📣', '💾', '❌', '🧠', '🔍', '🎉', '🧹', '🔗', '🗄️', '🔄', '⏳', '➡️', '📥', '📤']
        for emoji in emojis:
            full = full.replace(emoji, '')
        
        # Also clean up extra spaces that might be left behind
        # like println!("  Запуск") -> println!("Запуск")
        full = re.sub(r'println!\("\s+', 'println!("', full)
        
        return full

    content = re.sub(r'println!\(".*?"', clean_println, content)
    
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)

clean_file('feedo/feedo-core/src/main.rs')
