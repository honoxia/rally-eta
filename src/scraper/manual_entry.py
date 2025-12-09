"""Manual data entry helper for MVP"""
import pandas as pd
from pathlib import Path


def create_data_template():
    """Create Excel template for manual data entry"""

    template = pd.DataFrame({
        'rally_name': ['Example Rally 2024'],
        'rally_date': ['2024-03-15'],
        'stage_name': ['SS1'],
        'stage_number': [1],
        'stage_length_km': [18.5],
        'surface': ['gravel'],  # or 'asphalt'
        'day_or_night': ['day'],  # or 'night'
        'driver_name': ['Pilot Name'],
        'car_model': ['Ford Fiesta Rally2'],
        'car_class': ['Rally2'],  # R2, Rally2, R5, N4, etc.
        'time_str': ['10:23.4'],  # MM:SS.S format
        'status': ['FINISHED'],  # or DNF, DNS, DSQ
        'overall_position': [5],
        'class_position': [2],
    })

    output_path = Path('data/external/data_entry_template.xlsx')
    output_path.parent.mkdir(parents=True, exist_ok=True)
    template.to_excel(output_path, index=False)

    print(f"Template created: {output_path}")
    print("\nFill this template with rally data and save as 'rally_data.xlsx'")


def import_manual_data(file_path: str):
    """Import manually entered data"""
    from src.utils.database import Database
    from src.preprocessing.time_parser import TimeParser

    df = pd.read_excel(file_path)

    # Parse times
    parser = TimeParser()
    df['time_seconds'] = df['time_str'].apply(parser.parse)

    # Rename time_str to raw_time_str for database
    df['raw_time_str'] = df['time_str']
    df = df.drop(columns=['time_str'])

    # Rename position columns to match database schema
    df['overall_position_before'] = df['overall_position']
    df['class_position_before'] = df['class_position']
    df = df.drop(columns=['overall_position', 'class_position'])

    # Generate IDs
    df['rally_id'] = df['rally_name'].str.lower().str.replace(' ', '_')
    df['stage_id'] = df['rally_id'] + '_' + df['stage_name'].str.lower()
    df['driver_id'] = df['driver_name'].str.lower().str.replace(' ', '_')
    df['result_id'] = df['stage_id'] + '_' + df['driver_id']

    # Add missing columns with None/default values
    df['rally_year'] = pd.to_datetime(df['rally_date']).dt.year
    df['stage_number_in_day'] = df['stage_number']
    df['drive_type'] = None
    df['gap_to_leader_seconds'] = None
    df['gap_to_class_leader_seconds'] = None
    df['cumulative_stage_km'] = None
    df['is_anomaly'] = False
    df['anomaly_reason'] = None

    # Save to database
    db = Database()
    db.save_dataframe(df, 'stage_results', if_exists='append')

    print(f"Imported {len(df)} results")


if __name__ == '__main__':
    # Create template
    create_data_template()
