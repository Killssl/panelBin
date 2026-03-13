# ISO 3166-1 alpha-2 → официальное название в Binom
ISO_TO_BINOM: dict = {
    "AD": "Andorra", "AE": "United Arab Emirates", "AF": "Afghanistan",
    "AG": "Antigua and Barbuda", "AL": "Albania", "AM": "Armenia",
    "AO": "Angola", "AR": "Argentina", "AT": "Austria", "AU": "Australia",
    "AZ": "Azerbaijan", "BA": "Bosnia and Herzegovina", "BB": "Barbados",
    "BD": "Bangladesh", "BE": "Belgium", "BF": "Burkina Faso", "BG": "Bulgaria",
    "BH": "Bahrain", "BI": "Burundi", "BJ": "Benin", "BM": "Bermuda",
    "BN": "Brunei", "BO": "Bolivia", "BR": "Brazil", "BS": "Bahamas",
    "BT": "Bhutan", "BW": "Botswana", "BY": "Belarus", "BZ": "Belize",
    "CA": "Canada", "CD": "DR Congo", "CF": "Central African Republic",
    "CG": "Congo Republic", "CH": "Switzerland", "CI": "Ivory Coast",
    "CL": "Chile", "CM": "Cameroon", "CN": "China", "CO": "Colombia",
    "CR": "Costa Rica", "CU": "Cuba", "CV": "Cabo Verde", "CW": "Curaçao",
    "CY": "Cyprus", "CZ": "Czechia", "DE": "Germany", "DJ": "Djibouti",
    "DK": "Denmark", "DO": "Dominican Republic", "DZ": "Algeria",
    "EC": "Ecuador", "EE": "Estonia", "EG": "Egypt", "ES": "Spain",
    "ET": "Ethiopia", "FI": "Finland", "FJ": "Fiji", "FR": "France",
    "GA": "Gabon", "GB": "United Kingdom", "GD": "Grenada", "GE": "Georgia",
    "GF": "French Guiana", "GH": "Ghana", "GI": "Gibraltar", "GL": "Greenland",
    "GM": "Gambia", "GN": "Guinea", "GP": "Guadeloupe", "GQ": "Equatorial Guinea",
    "GR": "Greece", "GT": "Guatemala", "GU": "Guam", "GW": "Guinea-Bissau",
    "GY": "Guyana", "HK": "Hong Kong", "HN": "Honduras", "HR": "Croatia",
    "HT": "Haiti", "HU": "Hungary", "ID": "Indonesia", "IE": "Ireland",
    "IL": "Israel", "IM": "Isle of Man", "IN": "India", "IQ": "Iraq",
    "IR": "Iran", "IS": "Iceland", "IT": "Italy", "JE": "Jersey",
    "JM": "Jamaica", "JO": "Jordan", "JP": "Japan", "KE": "Kenya",
    "KG": "Kyrgyzstan", "KH": "Cambodia", "KR": "South Korea", "KW": "Kuwait",
    "KY": "Cayman Islands", "KZ": "Kazakhstan", "LA": "Laos", "LB": "Lebanon",
    "LC": "Saint Lucia", "LK": "Sri Lanka", "LR": "Liberia", "LS": "Lesotho",
    "LT": "Lithuania", "LU": "Luxembourg", "LV": "Latvia", "LY": "Libya",
    "MA": "Morocco", "MC": "Monaco", "MD": "Moldova", "ME": "Montenegro",
    "MG": "Madagascar", "MK": "North Macedonia", "ML": "Mali", "MM": "Myanmar",
    "MN": "Mongolia", "MO": "Macao", "MQ": "Martinique", "MR": "Mauritania",
    "MT": "Malta", "MU": "Mauritius", "MV": "Maldives", "MW": "Malawi",
    "MX": "Mexico", "MY": "Malaysia", "MZ": "Mozambique", "NA": "Namibia",
    "NC": "New Caledonia", "NE": "Niger", "NG": "Nigeria", "NI": "Nicaragua",
    "NL": "The Netherlands", "NO": "Norway", "NP": "Nepal", "NZ": "New Zealand",
    "OM": "Oman", "PA": "Panama", "PE": "Peru", "PF": "French Polynesia",
    "PH": "Philippines", "PK": "Pakistan", "PL": "Poland", "PR": "Puerto Rico",
    "PS": "Palestine", "PT": "Portugal", "PY": "Paraguay", "QA": "Qatar",
    "RE": "Réunion", "RO": "Romania", "RS": "Serbia", "RU": "Russia",
    "RW": "Rwanda", "SA": "Saudi Arabia", "SB": "Solomon Islands",
    "SC": "Seychelles", "SD": "Sudan", "SE": "Sweden", "SG": "Singapore",
    "SI": "Slovenia", "SK": "Slovakia", "SL": "Sierra Leone", "SN": "Senegal",
    "SO": "Somalia", "SR": "Suriname", "SS": "South Sudan",
    "ST": "São Tomé and Príncipe", "SV": "El Salvador", "SY": "Syria",
    "TD": "Chad", "TG": "Togo", "TH": "Thailand", "TJ": "Tajikistan",
    "TN": "Tunisia", "TR": "Türkiye", "TT": "Trinidad and Tobago",
    "TW": "Taiwan", "TZ": "Tanzania", "UA": "Ukraine", "UG": "Uganda",
    "UK": "United Kingdom", "US": "United States", "UY": "Uruguay",
    "UZ": "Uzbekistan", "VE": "Venezuela", "VN": "Vietnam", "XK": "Kosovo",
    "YE": "Yemen", "YT": "Mayotte", "ZA": "South Africa", "ZM": "Zambia",
    "ZW": "Zimbabwe",
}

# Быстрый обратный поиск: "türkiye" → "Türkiye"
_OFFICIAL_LOWER: dict = {v.lower(): v for v in ISO_TO_BINOM.values()}

# Алиасы: нестандартные/устаревшие названия → официальное название Binom
NAME_ALIASES: dict = {
    # Турция
    "turkey":               "Türkiye",
    "turkiye":              "Türkiye",
    # Нидерланды
    "netherlands":          "The Netherlands",
    "the netherlands":      "The Netherlands",
    "holland":              "The Netherlands",
    # Чехия
    "czech republic":       "Czechia",
    "czech":                "Czechia",
    # Берег слоновой кости
    "ivory coast":          "Ivory Coast",
    "cote d'ivoire":        "Ivory Coast",
    "cote divoire":         "Ivory Coast",
    # Кореи
    "south korea":          "South Korea",
    "korea":                "South Korea",
    # Конго
    "dr congo":             "DR Congo",
    "democratic republic of congo": "DR Congo",
    "drc":                  "DR Congo",
    "congo republic":       "Congo Republic",
    "republic of congo":    "Congo Republic",
    "congo":                "Congo Republic",
    # США
    "united states":        "United States",
    "usa":                  "United States",
    "us":                   "United States",
    # Великобритания
    "united kingdom":       "United Kingdom",
    "uk":                   "United Kingdom",
    "great britain":        "United Kingdom",
    "britain":              "United Kingdom",
    "england":              "United Kingdom",
    # ОАЭ
    "united arab emirates": "United Arab Emirates",
    "uae":                  "United Arab Emirates",
    # Филиппины
    "philippines":          "Philippines",
    "phillippines":         "Philippines",
    "philippenes":          "Philippines",
    # Бразилия
    "brazil":               "Brazil",
    "brasil":               "Brazil",
    # Остальные часто встречающиеся
    "russia":               "Russia",
    "france":               "France",
    "germany":              "Germany",
    "spain":                "Spain",
    "italy":                "Italy",
    "poland":               "Poland",
    "ukraine":              "Ukraine",
    "india":                "India",
    "pakistan":             "Pakistan",
    "indonesia":            "Indonesia",
    "mexico":               "Mexico",
    "kazakhstan":           "Kazakhstan",
    "uzbekistan":           "Uzbekistan",
    "azerbaijan":           "Azerbaijan",
    "armenia":              "Armenia",
    "georgia":              "Georgia",
    "belarus":              "Belarus",
    "moldova":              "Moldova",
    "kyrgyzstan":           "Kyrgyzstan",
    "tajikistan":           "Tajikistan",
    "bangladesh":           "Bangladesh",
    "malaysia":             "Malaysia",
    "thailand":             "Thailand",
    "vietnam":              "Vietnam",
    "myanmar":              "Myanmar",
    "cambodia":             "Cambodia",
    "mongolia":             "Mongolia",
    "egypt":                "Egypt",
    "morocco":              "Morocco",
    "algeria":              "Algeria",
    "nigeria":              "Nigeria",
    "ghana":                "Ghana",
    "kenya":                "Kenya",
    "senegal":              "Senegal",
    "canada":               "Canada",
    "australia":            "Australia",
    "japan":                "Japan",
    "china":                "China",
    "singapore":            "Singapore",
    "sweden":               "Sweden",
    "norway":               "Norway",
    "finland":              "Finland",
    "denmark":              "Denmark",
    "austria":              "Austria",
    "switzerland":          "Switzerland",
    "belgium":              "Belgium",
    "portugal":             "Portugal",
    "greece":               "Greece",
    "romania":              "Romania",
    "hungary":              "Hungary",
    "bulgaria":             "Bulgaria",
    "serbia":               "Serbia",
    "croatia":              "Croatia",
    "slovakia":             "Slovakia",
    "czechia":              "Czechia",
    "latvia":               "Latvia",
    "lithuania":            "Lithuania",
    "estonia":              "Estonia",
    "israel":               "Israel",
    "saudi arabia":         "Saudi Arabia",
    "iraq":                 "Iraq",
    "iran":                 "Iran",
    "jordan":               "Jordan",
    "lebanon":              "Lebanon",
    "kuwait":               "Kuwait",
    "qatar":                "Qatar",
    "bahrain":              "Bahrain",
    "oman":                 "Oman",
    "yemen":                "Yemen",
    "syria":                "Syria",
    "nepal":                "Nepal",
    "sri lanka":            "Sri Lanka",
    "afghanistan":          "Afghanistan",
    "myanmar":              "Myanmar",
    "laos":                 "Laos",
    "taiwan":               "Taiwan",
    "hong kong":            "Hong Kong",
    "south africa":         "South Africa",
    "ethiopia":             "Ethiopia",
    "tanzania":             "Tanzania",
    "uganda":               "Uganda",
    "cameroon":             "Cameroon",
    "tunisia":              "Tunisia",
    "libya":                "Libya",
    "sudan":                "Sudan",
    "somalia":              "Somalia",
    "zambia":               "Zambia",
    "zimbabwe":             "Zimbabwe",
    "argentina":            "Argentina",
    "colombia":             "Colombia",
    "chile":                "Chile",
    "peru":                 "Peru",
    "venezuela":            "Venezuela",
    "ecuador":              "Ecuador",
    "bolivia":              "Bolivia",
    "paraguay":             "Paraguay",
    "uruguay":              "Uruguay",
}

# Ключевые слова мульти-GEO правил — такие rule не матчатся с одной страной
_MULTIGEO_KEYWORDS = (
    "multigeo", "multi geo", "multi-geo",
    "european union", " eu)", "(eu)", "not eu", "not ca", "not us", "not ru",
    "worldwide", "world wide", "ww", "global",
    "tier1", "tier 1", "tier2", "tier 3",
    "all countries", "other", "default",
    "privacy page", "privacy",
)


def is_multigeo_rule(name: str) -> bool:
    """True если rule охватывает несколько стран — не одну конкретную."""
    n = name.lower().strip()
    return any(kw in n for kw in _MULTIGEO_KEYWORDS)


def resolve_geo_name(rule_name: str, country_map: dict = None) -> str:
    """
    Превращает название GEO из rule в официальное название Binom.

    Приоритет:
    1. ISO код в строке  "Turkey TR" → TR → "Türkiye"
    2. Алиас по имени   "Turkey"    → "Türkiye"
    3. Точное совпадение официального имени (регистронезависимо)
    4. Возвращаем как есть
    """
    name = rule_name.strip()
    cmap = country_map or ISO_TO_BINOM

    # 1. Ищем 2-буквенный ISO код в строке
    for part in name.replace("/", " ").split():
        if len(part) == 2 and part.isalpha():
            mapped = cmap.get(part.upper()) or ISO_TO_BINOM.get(part.upper())
            if mapped:
                return mapped

    # 2. Алиас
    norm = name.lower().strip()
    if norm in NAME_ALIASES:
        return NAME_ALIASES[norm]

    # 3. Официальное имя (регистронезависимо)
    official = _OFFICIAL_LOWER.get(norm)
    if official:
        return official

    # 4. Как есть
    return name