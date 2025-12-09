from pathlib import Path

from src.scraper.tosfed_sonuc_scraper import parse_html


def main():
    html_path = Path("data/debug_tosfed_97.html")
    html_text = html_path.read_text(encoding="utf-8")

    df = parse_html(html_text)

    print(f"Row count: {len(df)}")
    print(df.head())


if __name__ == "__main__":
    main()
