import sqlite3

conn = sqlite3.connect('rally_data.db')
cursor = conn.cursor()

print("=" * 90)
print("8.25 KM CİVARINDAKİ ETAPLARDA SINIF LİDERLERİNİN ZAMANLARI")
print("=" * 90)

# 8.25 km civarındaki etaplarda sınıf liderlerinin zamanları
cursor.execute('''
SELECT
    stage_name,
    stage_length_km,
    car_class,
    MIN(time_seconds) as class_best_time,
    MIN(time_seconds) / stage_length_km as time_per_km
FROM clean_stage_results
WHERE stage_length_km BETWEEN 5.8 AND 12.4
  AND surface = 'gravel'
  AND time_seconds > 0
GROUP BY stage_name, stage_length_km, car_class
ORDER BY stage_length_km, car_class
LIMIT 30
''')

print(f"{'Etap Adı':<30} | {'Uzunluk':>8} | {'Sınıf':>8} | {'En İyi':>8} | {'s/km':>8}")
print("-" * 90)

for row in cursor.fetchall():
    stage_name = row[0][:30] if row[0] else "N/A"
    length = row[1]
    car_class = row[2]
    best_time = row[3]
    time_per_km = row[4]

    minutes = int(best_time // 60)
    seconds = best_time % 60

    print(f"{stage_name:<30} | {length:6.2f} km | {car_class:>8} | {minutes}:{seconds:05.2f} | {time_per_km:6.2f} s/km")

print("\n" + "=" * 90)
print("REFERANS ZAMAN HESAPLAMA TEST")
print("=" * 90)

# Referans zaman hesabını test et (8.25 km için)
cursor.execute('''
WITH stage_class_best AS (
    SELECT stage_id, car_class, MIN(time_seconds) as class_best_time
    FROM clean_stage_results
    WHERE time_seconds > 0
    GROUP BY stage_id, car_class
)
SELECT
    MIN(s.class_best_time / c.stage_length_km) as best_speed_time_per_km,
    COUNT(*) as sample_count
FROM clean_stage_results c
INNER JOIN stage_class_best s
    ON c.stage_id = s.stage_id AND c.car_class = s.car_class
WHERE c.car_class = 'Rally2'
AND c.surface = 'gravel'
AND c.stage_length_km BETWEEN 5.775 AND 12.375
AND c.stage_length_km > 0
''')

result = cursor.fetchone()
if result[0]:
    best_time_per_km = result[0]
    sample_count = result[1]
    ref_time_for_8_25 = best_time_per_km * 8.25

    ref_minutes = int(ref_time_for_8_25 // 60)
    ref_seconds = ref_time_for_8_25 % 60

    print(f"\n8.25 km gravel etap için Rally2 sınıfı:")
    print(f"  - En hızlı: {best_time_per_km:.2f} s/km")
    print(f"  - Referans zaman: {ref_minutes}:{ref_seconds:05.2f} ({ref_time_for_8_25:.1f}s)")
    print(f"  - Sample sayısı: {sample_count}")
    print(f"\n  ⚠️  Bu referans zaman GERÇEK sınıf liderinin zamanı olmalı!")

conn.close()
