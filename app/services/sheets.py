"""
Утилита сравнения имён офферов (Binom ↔ партнёрские названия).
Google Sheets API удалён — используется только _names_match.
"""
import re


def _names_match(binom_name: str, sheet_name: str) -> bool:
    def clean(s):
        s = re.sub(r'\[CAP[^\]]*\]', '', s, flags=re.I)
        s = re.sub(r'\bCAP\d+[!]?', '', s, flags=re.I)
        s = re.sub(r'\b\d+/day[!]?', '', s, flags=re.I)
        s = re.sub(r'[^\w\s]', ' ', s)
        words = [w for w in s.lower().split() if len(w) >= 2]
        return words

    bn = clean(binom_name)
    sn = clean(sheet_name)
    if not bn or not sn:
        return False

    bn_set = set(bn)
    sn_set = set(sn)

    if len(bn) <= len(sn):
        short, long_set, long = bn, sn_set, sn
    else:
        short, long_set, long = sn, bn_set, bn

    if len(long) > len(short) * 1.5 and len(short) < 4:
        return False
    if len(short) < 2:
        return False

    overlap = sum(1 for w in short if w in long_set)
    ratio   = overlap / len(short)
    return ratio >= 0.85 and overlap >= 2


# ── Fill Binom IDs ────────────────────────────────────────────────────────────
