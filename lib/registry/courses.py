"""Wash, dry and dishwasher cycle names, keyed by the appliance's own course table.

The appliance reports the running cycle as a hex code in `/course/vs/0`'s options[]
(`Course_1C`), and **the same code means different things on different boards** — not
only between a washer and a dryer, but between board generations of the same
appliance. Washer Table_00 and Table_02 share eleven codes and ten of them disagree
(`70` is Heavy Duty on one and Towels on the other). So a code is only meaningful
together with the table it came from, which the appliance names itself in
`/st/washercourse/vs/0` or `/st/dryercourse/vs/0`.

That is why there is one Homey capability per table rather than one per appliance.
Homey declares an enum's values, with their names, in the manifest — so a single id
cannot carry two tables' meanings, and prefixing ids by table would have meant
renaming values already published in 1.0.8. For the reference this is a
translations-only concern because Home Assistant resolves labels at runtime; here it
is structural.

Only tables somebody has actually confirmed are here. A board reporting a table
nobody has named gets no cycle rather than a label borrowed from another generation
— the FlexWash reports `Table_00_Course_A5`, and `a5` is a dryer Table_00 code, not
a washer one, so it stays blank.

Both catalogs come from the reference, which built Table_02/Table_03 from reporters'
SmartThings screenshots and Table_00 from a reporter selecting each cycle on a
WF45R6300 washer and DVE45R6300 dryer and reading back the raw code. Transcribed
here rather than re-derived; a missing code shows as no cycle, which is a gap in the
catalog rather than a wrong reading.
"""

WASHER_TABLE_00 = {
    "01": {"en": "Normal", "ko": "표준세탁"},
    "55": {"en": "Whites", "ko": "흰옷"},
    "57": {"en": "Self Clean+", "ko": "통세척+"},
    "70": {"en": "Heavy Duty", "ko": "강력세탁"},
    "71": {"en": "Bedding", "ko": "이불"},
    "72": {"en": "Sanitize", "ko": "살균"},
    "73": {"en": "Rinse + Spin", "ko": "헹굼+탈수"},
    "74": {"en": "Active Wear", "ko": "운동복"},
    "75": {"en": "Delicates", "ko": "섬세의류"},
    "77": {"en": "Perm Press", "ko": "구김방지"},
    "78": {"en": "Quick Wash", "ko": "쾌속세탁"},
}

WASHER_TABLE_02 = {
    "01": {"en": "Normal", "ko": "표준세탁"},
    "02": {"en": "Extra Heavy Duty", "ko": "초강력세탁"},
    "03": {"en": "Super Eco Wash", "ko": "초절약세탁"},
    "04": {"en": "Quick Wash", "ko": "쾌속세탁"},
    "05": {"en": "Wool/Lingerie", "ko": "울/란제리"},
    "06": {"en": "Bedding", "ko": "이불"},
    "07": {"en": "Outdoor", "ko": "아웃도어"},
    "08": {"en": "Rinse+Spin", "ko": "헹굼+탈수"},
    "09": {"en": "Drum Clean", "ko": "무세제통세척"},
    "0a": {"en": "Towels", "ko": "타월"},
    "0b": {"en": "Boil Wash", "ko": "삶음세탁"},
    "0c": {"en": "Baby Care", "ko": "아기옷"},
    "0d": {"en": "Spin Only", "ko": "탈수단독"},
    "0e": {"en": "Cloudy Day", "ko": "흐린날세탁"},
    "0f": {"en": "Pure Wash", "ko": "청정세탁"},
    "10": {"en": "Spin Dry", "ko": "건조탈수"},
    "11": {"en": "Summer Bedding", "ko": "여름이불"},
    "12": {"en": "Cottons", "ko": "면의류"},
    "13": {"en": "Black Cottons", "ko": "검은면의류"},
    "14": {"en": "Delicate Underwear", "ko": "섬세속옷"},
    "15": {"en": "Activewear", "ko": "피트니스"},
    "16": {"en": "Blouses", "ko": "블라우스"},
    "17": {"en": "Downloaded", "ko": "다운로드 코스"},
    "18": {"en": "Soft Bubble", "ko": "소프트버블"},
    "19": {"en": "AI Wash", "ko": "AI 맞춤세탁"},
    "1a": {"en": "Shirts", "ko": "셔츠"},
    "1b": {"en": "Cotton", "ko": "면"},
    "1c": {"en": "Eco 40-60", "ko": "에코 40-60"},
    "1d": {"en": "Super Speed", "ko": "쾌속세탁"},
    "1e": {"en": "15' Quick Wash", "ko": "15분 쾌속세탁"},
    "1f": {"en": "Intense Cold", "ko": "강력 냉수 세탁"},
    "20": {"en": "Hygiene Steam", "ko": "살균세탁"},
    "21": {"en": "Colors", "ko": "컬러 의류"},
    "22": {"en": "Wool", "ko": "울"},
    "23": {"en": "Outdoor", "ko": "아웃도어"},
    "24": {"en": "Bedding", "ko": "이불"},
    "25": {"en": "Synthetics", "ko": "합성섬유"},
    "26": {"en": "Delicates", "ko": "섬세의류"},
    "27": {"en": "Rinse+Spin", "ko": "헹굼+탈수"},
    "28": {"en": "Drain/Spin", "ko": "배수/탈수"},
    "29": {"en": "Drum Clean+", "ko": "무세제통세척+"},
    "2a": {"en": "Jeans", "ko": "청바지"},
    "2b": {"en": "AI Wash", "ko": "AI 맞춤세탁"},
    "2d": {"en": "Silent Wash", "ko": "조용히 세탁"},
    "2e": {"en": "Baby Care", "ko": "아기옷"},
    "2f": {"en": "Activewear", "ko": "피트니스"},
    "30": {"en": "Cloudy Day", "ko": "흐린 날"},
    "32": {"en": "Shirts", "ko": "셔츠"},
    "33": {"en": "Towels", "ko": "타월"},
    "34": {"en": "Mixed", "ko": "혼합"},
    "35": {"en": "E Cotton", "ko": "에코 면"},
    "36": {"en": "Wash+Dry", "ko": "세탁+건조"},
    "37": {"en": "Air Wash", "ko": "에어워시"},
    "38": {"en": "Cotton Dry", "ko": "면 건조"},
    "39": {"en": "Synthetics Dry", "ko": "합성섬유 건조"},
    "3a": {"en": "Drum Clean", "ko": "무세제통세척"},
    "52": {"en": "Eco Cold", "ko": "에코 냉수 세탁"},
    "53": {"en": "Heavy Duty", "ko": "강력세탁"},
    "54": {"en": "Towels", "ko": "타월"},
    "55": {"en": "Activewear", "ko": "피트니스"},
    "57": {"en": "Delicate", "ko": "섬세의류"},
    "5e": {"en": "Rinse+Spin", "ko": "헹굼+탈수"},
    "60": {"en": "Self Clean+", "ko": "통세척+"},
    "65": {"en": "Colors", "ko": "컬러 의류"},
    "66": {"en": "Denim", "ko": "데님"},
    "69": {"en": "AI Wash", "ko": "AI 맞춤세탁"},
    "6a": {"en": "Wool", "ko": "울"},
    "6b": {"en": "Denim", "ko": "데님"},
    "6c": {"en": "Blouses", "ko": "블라우스"},
    "6d": {"en": "Delicates", "ko": "섬세의류"},
    "6e": {"en": "Active Wear", "ko": "운동복"},
    "6f": {"en": "Bedding", "ko": "이불"},
    "70": {"en": "Towels", "ko": "타월"},
    "71": {"en": "Quick Wash", "ko": "쾌속세탁"},
    "72": {"en": "Shirts", "ko": "셔츠"},
    "73": {"en": "Sanitize", "ko": "살균"},
    "74": {"en": "Drum Clean", "ko": "무세제통세척"},
    "75": {"en": "Outdoor", "ko": "아웃도어"},
    "76": {"en": "Baby Care", "ko": "아기옷"},
    "77": {"en": "Cottons", "ko": "면"},
    "78": {"en": "Rinse + Spin", "ko": "헹굼+탈수"},
    "79": {"en": "Spin Only", "ko": "탈수만"},
    "7c": {"en": "Whites", "ko": "흰옷"},
    "7d": {"en": "Bedding/Waterproof", "ko": "이불/방수 의류"},
    "7e": {"en": "Self-Clean", "ko": "통세척"},
    "7f": {"en": "Wool/Delicate", "ko": "울/섬세"},
    "86": {"en": "Deep Wash", "ko": "찌든 때 세탁"},
    "87": {"en": "Download", "ko": "다운로드"},
    "88": {"en": "Pet Care", "ko": "펫케어"},
    "8f": {"en": "Intense Cold", "ko": "강력 냉수 세탁"},
    "96": {"en": "Less Microfiber", "ko": "미세플라스틱저감"},
    "a0": {"en": "15' Quick Wash", "ko": "15분 쾌속세탁"},
    "b0": {"en": "Mixed Load", "ko": "혼합 세탁"},
}

DRYER_TABLE_00 = {
    "01": {"en": "Normal", "ko": "표준건조"},
    "27": {"en": "Refresh", "ko": "리프레시"},
    "9b": {"en": "Steam Sanitize+", "ko": "스팀살균+"},
    "9c": {"en": "Heavy Duty", "ko": "강력건조"},
    "9e": {"en": "Perm Press", "ko": "구김방지"},
    "a0": {"en": "Air Fluff", "ko": "송풍"},
    "a2": {"en": "Delicates", "ko": "섬세의류"},
    "a3": {"en": "Active Wear", "ko": "운동복"},
    "a4": {"en": "Time Dry", "ko": "시간건조"},
    "a5": {"en": "Bedding", "ko": "이불"},
    "a6": {"en": "Quick Dry", "ko": "쾌속건조"},
}

DRYER_TABLE_03 = {
    "01": {"en": "Normal", "ko": "표준건조"},
    "02": {"en": "AI Dry", "ko": "AI 맞춤건조"},
    "03": {"en": "Super Speed", "ko": "쾌속건조"},
    "05": {"en": "Bedding", "ko": "이불"},
    "06": {"en": "Time dry", "ko": "시간건조"},
    "07": {"en": "Delicates", "ko": "섬세의류"},
    "09": {"en": "Shirts", "ko": "셔츠"},
    "0b": {"en": "Padding Care", "ko": "패딩케어"},
    "0c": {"en": "Outdoor Water-Repellent Care", "ko": "아웃도어발수케어"},
    "0e": {"en": "Towels", "ko": "타월"},
    "0f": {"en": "Wool", "ko": "울"},
    "11": {"en": "Cool air", "ko": "송풍건조"},
    "16": {"en": "Cotton", "ko": "면의류"},
    "17": {"en": "Super Speed", "ko": "쾌속건조"},
    "18": {"en": "Synthetics", "ko": "합성섬유"},
    "19": {"en": "Delicates", "ko": "섬세의류"},
    "1a": {"en": "Wool", "ko": "울"},
    "1b": {"en": "Bedding", "ko": "이불"},
    "1c": {"en": "Shirts", "ko": "셔츠"},
    "1d": {"en": "Towels", "ko": "타월"},
    "1e": {"en": "Outdoor", "ko": "아웃도어"},
    "1f": {"en": "Mixed load", "ko": "혼합"},
    "20": {"en": "Iron dry", "ko": "다림질건조"},
    "21": {"en": "Hygiene Care", "ko": "살균건조"},
    "22": {"en": "Silent Dry", "ko": "조용히 건조"},
    "23": {"en": "Quick Dry 35'", "ko": "쾌속건조 35분"},
    "24": {"en": "Cool air", "ko": "송풍건조"},
    "25": {"en": "Warm air", "ko": "온풍건조"},
    "26": {"en": "Air wash", "ko": "송풍"},
    "27": {"en": "Time dry", "ko": "시간건조"},
    "28": {"en": "Interior Hot Air Sanitize", "ko": "열풍내부살균"},
    "29": {"en": "AI Dry", "ko": "AI 맞춤건조"},
    "2a": {"en": "Hygiene Care+", "ko": "살균건조+"},
    "2b": {"en": "Self Tub Dry", "ko": "통 건조"},
    "37": {"en": "Blouses", "ko": "블라우스"},
    "38": {"en": "Iron dry", "ko": "다림질건조"},
    "39": {"en": "Room Dehumidify", "ko": "공간제습"},
    "3a": {"en": "Hygiene Care", "ko": "살균건조"},
    "3b": {"en": "Bedding/Dust Off", "ko": "이불/먼지털기"},
    "3c": {"en": "Activewear", "ko": "피트니스"},
    "3d": {"en": "Denim", "ko": "데님"},
    "4c": {"en": "Air Refresh", "ko": "에어 리프레시"},
    "4e": {"en": "Self Dry", "ko": "자체 건조"},
    "51": {"en": "Eco Cotton", "ko": "에코 면"},
    "53": {"en": "AI Dry+", "ko": "AI 맞춤건조+"},
}

DISHWASHER = {
    "07": {"en": "Pre blast", "ko": "애벌 세척"},
    "0c": {"en": "Express", "ko": "급속"},
    "0d": {"en": "Self clean", "ko": "내부 세척"},
    "0e": {"en": "AI Wash", "ko": "AI 맞춤 세척"},
    "80": {"en": "Delicate", "ko": "섬세"},
    "82": {"en": "Auto", "ko": "자동"},
    "83": {"en": "Normal", "ko": "표준"},
    "84": {"en": "Heavy", "ko": "강력"},
    "85": {"en": "Delicate", "ko": "섬세"},
    "86": {"en": "Express 60", "ko": "급속 60분"},
    "88": {"en": "Self Clean", "ko": "내부 세척"},
    "8a": {"en": "Normal", "ko": "표준"},
    "8c": {"en": "Extra Silence", "ko": "저소음"},
    "8d": {"en": "Pots and pans", "ko": "냄비 및 팬"},
    "8e": {"en": "Plastic", "ko": "플라스틱"},
    "8f": {"en": "Baby Care", "ko": "젖병 살균"},
    "90": {"en": "Self clean", "ko": "내부 세척"},
    "a7": {"en": "Heavy", "ko": "강력"},
    "a8": {"en": "Express", "ko": "급속"},
}

# (resource, table id) -> the catalog and the Homey capability that carries it.
# Keyed by the resource because that names the family and by the id because that
# names the generation. A one-body washer-dryer reports both resources and binds
# both capabilities, which is measured rather than assumed.
BY_TABLE = {
    ("washercourse", "table_00"): ("localthings_wash_cycle_t00", WASHER_TABLE_00),
    ("washercourse", "table_02"): ("localthings_wash_cycle", WASHER_TABLE_02),
    ("dryercourse", "table_00"): ("localthings_dry_cycle_t00", DRYER_TABLE_00),
    ("dryercourse", "table_03"): ("localthings_dry_cycle", DRYER_TABLE_03),
}
