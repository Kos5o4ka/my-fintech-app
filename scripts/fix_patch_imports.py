import os
import re

ROOT = "/root/my_web_app/tests"

TARGETS = [
    "models",
    "extensions",
    "config",
    "constants",
    "utils",
    "cbr",
    "moex",
    "blueprints",
    "schemas",
    "services",
]


def process_file(filepath):
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    new_content = content
    for target in TARGETS:
        new_content = re.sub(
            rf'patch\("{target}\.', f'patch("app.{target}.', new_content
        )
        new_content = re.sub(
            rf"patch\(\'{target}\.", f"patch('app.{target}.", new_content
        )

        # also patch("moex")
        new_content = re.sub(
            rf'patch\("{target}"\)', f'patch("app.{target}")', new_content
        )
        new_content = re.sub(
            rf"patch\(\'{target}\'\)", f"patch('app.{target}')", new_content
        )

    if new_content != content:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(new_content)
        print(f"Fixed patches in {filepath}")


for root, _, files in os.walk(ROOT):
    for file in files:
        if file.endswith(".py"):
            process_file(os.path.join(root, file))

print("Done")
