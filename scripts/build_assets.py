import re
from pathlib import Path

JS_FILES = [
    "static/js/core/common.js",
    "static/js/core/sidebar.js",
    "static/js/core/base.js",
    # Per-page bundles
    "static/js/pages/portfolio.js",
    "static/js/pages/dashboard.js",
    "static/js/pages/profile.js",
    "static/js/pages/landing.js",
    "static/js/pages/portfolio-page.js",
    "static/js/pages/admin.js",
    "static/js/pages/analytics.js",
    "static/js/pages/import.js",
]
CSS_FILES = [
    "static/css/core/variables.css",
    "static/css/core/sidebar.css",
    "static/css/core/animations.css",
    "static/css/core/base.css",
    # Per-page stylesheets
    "static/css/pages/portfolio.css",
    "static/css/pages/dashboard.css",
    "static/css/pages/profile.css",
    "static/css/pages/landing.css",
    "static/css/pages/portfolio-page.css",
]


def minify_js(content: str) -> str:
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
