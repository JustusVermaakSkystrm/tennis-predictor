"""build_site.py — regenerate docs/index.html from the latest data.

Entry point for the (eventual) hourly workflow:
    ./scripts/fetch_data.sh && ./scripts/fetch_odds.sh && python -m scripts.build_site
"""
from tennis import site

if __name__ == "__main__":
    site.build()
    print("Wrote docs/index.html")
