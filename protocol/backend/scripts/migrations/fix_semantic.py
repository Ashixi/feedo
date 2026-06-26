import sys

path = 'api_v1/semantic.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# Add import if not present
if "from utils.nsfw_filter import is_nsfw" not in content:
    import_stmt = "import sys\nimport os\nsys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))\nfrom utils.nsfw_filter import is_nsfw\n"
    content = import_stmt + content

# Replace all occurrences of "for r in search_res:" to include the filter
old_str = "for r in search_res:"
new_str = 'for r in search_res:\n            if is_nsfw(r.get("text", "")) or is_nsfw(r.get("content", "")):\n                continue'

content = content.replace(old_str, new_str)

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)

print("Fixed semantic.py!")
