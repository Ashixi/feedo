import re

def remove_comments(line):
    # Quick heuristic to remove trailing comments // while ignoring those in quotes
    # and not touching /// or //! or ://
    if "://" in line:
        return line
    if "///" in line or "//!" in line:
        return line
        
    parts = line.split("//")
    if len(parts) == 1:
        return line
        
    # Reconstruct the line up to the first // that has an even number of quotes before it
    before = parts[0]
    for i in range(1, len(parts)):
        quotes_count = before.count('"') - before.count('\\"')
        if quotes_count % 2 == 0:
            # We found a valid comment start
            # If the part was entirely whitespace before the comment, return just \n
            if before.strip() == "":
                return ""
            return before.rstrip() + "\n"
        else:
            before += "//" + parts[i]
            
    return line

def clean_file(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    emoji_pattern = re.compile(
        "["
        "\U0001f600-\U0001f64f"
        "\U0001f300-\U0001f5ff"
        "\U0001f680-\U0001f6ff"
        "\U0001f1e0-\U0001f1ff"
        "\u2702-\u27b0"
        "\U0001f900-\U0001f9ff"
        "\U0001fa70-\U0001faff"
        "\u2600-\u26ff"
        "\u2700-\u27bf"
        "]+",
        flags=re.UNICODE
    )

    new_lines = []
    for line in lines:
        line = remove_comments(line)
        if line == "":
            continue
            
        line = emoji_pattern.sub(r'', line)
        
        # fix spacing in println!
        line = re.sub(r'println!\("\s+', 'println!("', line)
        line = re.sub(r'println!\("(.*?)\s+"', r'println!("\1"', line)
        line = line.replace('  ', ' ')
        
        new_lines.append(line)

    # ensure no more than 2 empty lines
    content = "".join(new_lines)
    content = re.sub(r'\n{3,}', '\n\n', content)

    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)

clean_file('feedo/feedo-core/src/main.rs')
