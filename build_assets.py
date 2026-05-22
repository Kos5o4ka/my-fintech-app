import re
from pathlib import Path

JS_FILES = [
    "static/js/common.js",
    "static/js/index.js",
    "static/js/portfolio.js",
    "static/js/sidebar.js",
]
CSS_FILES = [
    "static/css/variables.css",
    "static/css/sidebar.css",
    "static/css/animations.css",
    "static/css/portfolio.css",
]


def minify_js(content: str) -> str:
    # Remove block comments and line comments, preserve strings and regex-like content roughly.
    content = re.sub(r"/\*[\s\S]*?\*/", "", content)
    content = re.sub(r"(?m)//.*?$", "", content)
    content = re.sub(r"\s+", " ", content)
    content = re.sub(r"\s*([{}();,:+\-\[\]=<>])\s*", r"\1", content)
    return content.strip()


def minify_css(content: str) -> str:
    content = re.sub(r"/\*[\s\S]*?\*/", "", content)
    content = re.sub(r"\s+", " ", content)
    content = re.sub(r"\s*([{}:;,])\s*", r"\1", content)
    content = re.sub(r";\}", "}", content)
    return content.strip()


def write_minified(path: Path, minified: str):
    out_path = path.with_name(path.stem + ".min" + path.suffix)
    out_path.write_text(minified, encoding="utf-8")
    print(f"Written {out_path}")


def main():
    cwd = Path(__file__).resolve().parent
    for src in JS_FILES:
        path = cwd / src
        if not path.exists():
            print(f"Skipping missing {path}")
            continue
        write_minified(path, minify_js(path.read_text(encoding="utf-8")))
    for src in CSS_FILES:
        path = cwd / src
        if not path.exists():
            print(f"Skipping missing {path}")
            continue
        write_minified(path, minify_css(path.read_text(encoding="utf-8")))


if __name__ == "__main__":
    main()
