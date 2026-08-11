"""Wash, dry and dishwasher cycle names, keyed by the appliance's own course table.

The appliance reports the running cycle as a hex code in `/course/vs/0`'s options[]
(`Course_1C`), and **the same code means different things on different boards**. A
washer and a dryer share twenty codes and not one of them agrees: `01` is Normal
wash or Normal dry, `1d` is Quick wash or Towels. So a code is only meaningful
together with the table it came from, which the appliance names itself in
`/st/washercourse/vs/0` or `/st/dryercourse/vs/0`'s `courseTable`.

Only the tables somebody has actually seen labelled are here. A board reporting
`Table_00` (FlexWash) or a table nobody has translated gets its raw code shown
rather than a label borrowed from another generation — which is the failure this
keying exists to prevent, not a limitation of it.

Both catalogs come from the reference integration, which built them from reporters'
own SmartThings screenshots. They are transcribed here rather than re-derived; where
a code is missing, the raw code is displayed and that is a gap in the catalog rather
than a wrong reading.
"""

WASHER_TABLE_02 = {
    "01": {"en": "Normal", "ko": "표준세탁"},
    "04": {"en": "Quick Wash", "ko": "쾌속세탁"},
    "06": {"en": "XXL Laundry", "ko": "XXL 세탁"},
    "08": {"en": "Rinse+Spin", "ko": "헹굼+탈수"},
    "17": {"en": "Downloaded", "ko": "다운로드 코스"},
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
}

DRYER_TABLE_03 = {
    "01": {"en": "Normal", "ko": "표준건조"},
    "06": {"en": "Time dry", "ko": "시간건조"},
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
    "29": {"en": "AI Dry", "ko": "AI 맞춤건조"},
    "2a": {"en": "Hygiene Care+", "ko": "살균건조+"},
    "2b": {"en": "Self Tub Dry", "ko": "통 건조"},
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

# Which catalog a device's own `courseTable` selects. Keyed by (resource, table id)
# because the resource names the family and the id names the generation; a
# washer-dryer combo reports `dryercourse` and is labelled from the dryer catalog,
# which is measured rather than assumed — `washer_dryer_onebody_awm` does exactly
# that.
BY_TABLE = {
    ("washercourse", "table_02"): WASHER_TABLE_02,
    ("dryercourse", "table_03"): DRYER_TABLE_03,
}
