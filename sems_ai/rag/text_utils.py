"""Normalización de texto, palabras vacías ES/EN y detección simple de idioma."""
from __future__ import annotations

import re
import unicodedata

STOP_ES = set("""a al algo algunas algunos ante antes como con contra cual cuales cuando de del desde donde dos
el ella ellas ellos en entre era es esa esas ese eso esos esta estas este esto estos fue fueron ha han hasta hay
la las le les lo los mas más me mi mis muy ni no nos o otra otras otro otros para pero por que qué se sea sean
segun según ser si sí sin sobre su sus también tanto te tiene tienen todo todos tu un una unas uno unos y ya
cada debe deben deberá deberán será serán dicho dicha dichos dichas así mismo misma etc través
""".split())
STOP_EN = set("""a about above after all also an and any are as at be been before being below between both but by
can could did do does each for from had has have he her here his how i if in into is it its may more most must
no nor not of on once only or other our out over own same shall she should so some such than that the their them
then there these they this those through to too under until up very was we were what when where which while who
will with would you your per within upon
""".split())
STOPWORDS = STOP_ES | STOP_EN


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", strip_accents(text.lower()))


def stem(w: str) -> str:
    """Stemming ligero (sufijos comunes ES/EN) para comparaciones léxicas."""
    for suf in ("aciones", "iciones", "amiento", "imiento", "mente", "ciones", "cion", "sion", "ings", "ing",
                "ation", "ations", "ments", "ment", "idad", "ades", "edad", "es", "s", "ed", "ly"):
        if len(w) > len(suf) + 3 and w.endswith(suf):
            return w[: -len(suf)]
    return w


def keywords(text: str, min_len: int = 3) -> list[str]:
    return [t for t in tokens(text) if len(t) >= min_len and t not in STOPWORDS and not t.isdigit()]


def stems(text: str) -> set[str]:
    return {stem(t) for t in keywords(text)}


def detect_language(text: str) -> str:
    toks = tokens(text[:20000])
    es = sum(1 for t in toks if t in STOP_ES)
    en = sum(1 for t in toks if t in STOP_EN)
    if es == en == 0:
        return "desconocido"
    return "es" if es >= en else "en"


def fts_query(text: str, max_terms: int = 24, mode: str = "OR") -> str:
    """Construye una consulta FTS5 segura (sin operadores inyectados por el usuario)."""
    terms = []
    for t in keywords(text, 2):
        if t not in terms:
            terms.append(t)
    terms = terms[:max_terms]
    if not terms:
        return ""
    # prefijo para palabras largas → tolera plural/singular
    parts = [f'"{t}"*' if len(t) > 4 else f'"{t}"' for t in terms]
    return f" {mode} ".join(parts)
