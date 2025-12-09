from pathlib import Path

import pandas as pd

from src.scraper.tosfed_sonuc_scraper import TOSFEDSonucScraper


def rally_to_dataframe(rally_data) -> pd.DataFrame:
    """Convert rally_data dict from the scraper into a DataFrame."""
    if not rally_data:
        return pd.DataFrame()

    rows = []
    rally_id = rally_data.get("rally_id")
    rally_name = rally_data.get("rally_name")

    for stage in rally_data.get("stages", []):
        stage_number = stage.get("stage_number")
        for result in stage.get("results", []):
            rows.append(
                {
                    "rally_id": rally_id,
                    "rally_name": rally_name,
                    "stage_name": stage.get("stage_name"),
                    "stage_number": stage_number,
                    "stage_length_km": stage.get("stage_length_km"),
                    "position": result.get("position"),
                    "car_number": result.get("car_number"),
                    "driver_name": result.get("driver_name"),
                    "nationality": result.get("nationality"),
                    "car_class": result.get("car_class"),
                    "team": result.get("team"),
                    "car_model": result.get("car_model"),
                    "time_str": result.get("time_str"),
                    "time_diff": result.get("time_diff"),
                    "status": result.get("status"),
                }
            )

    return pd.DataFrame(rows)


def main():
    rally_id = 97  # Example rally ID used in the Streamlit app

    scraper = TOSFEDSonucScraper()
    rally_data = scraper.fetch_rally_stages(rally_id)

    df = rally_to_dataframe(rally_data)

    print("SCRAPER ROWS:", len(df))
    print(df.head())

    output_path = Path("data") / "scraper_debug_97.xlsx"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_excel(output_path, index=False)

    print(f"Saved Excel to: {output_path}")


if __name__ == "__main__":
    main()
