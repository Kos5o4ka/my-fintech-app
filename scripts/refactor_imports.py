import os
import re

ROOT = "/root/my_web_app"

TARGETS = ["models", "extensions", "config", "constants", "utils", "cbr", "moex", "blueprints", "schemas", "services"]

def process_file(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    new_content = content
    for target in TARGETS:
        # Avoid double replacing if it's already from app.xxx
        # We only match when it's literally `from models` or `import models` etc.
        # \g<1> retains the leading whitespace.
        new_content = re.sub(r'^([ \t]*)from ' + target + r'\b', r'\g<1>from app.' + target, new_content, flags=re.MULTILINE)
        new_content = re.sub(r'^([ \t]*)import ' + target + r'\b', r'\g<1>from app import ' + target, new_content, flags=re.MULTILINE)

    if new_content != content:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print(f"Updated {filepath}")

for root, _, files in os.walk(ROOT):
    if '.venv' in root or 'venv' in root or '__pycache__' in root or '.git' in root or 'scripts' in root:
        continue
    for file in files:
        if file.endswith('.py'):
            process_file(os.path.join(root, file))

print("Done")
