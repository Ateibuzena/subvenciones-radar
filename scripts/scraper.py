"""
====================================================
 MONITOR DE AYUDAS Y SUBVENCIONES PARA EMPRESAS
 Scraper: BOE + Boletines Autonómicos
====================================================
"""

import json
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from dataclasses import dataclass, asdict, field
import logging
import hashlib
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from typing import Optional

import spacy
from dateutil import parser as dateutil_parser

# ── Configuración ─────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR.parent / "data"
DATA_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[
        logging.FileHandler(BASE_DIR.parent / "scraper.log"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("subvenciones")

# ── Palabras clave ─────────────────────────────────────────────────────────────

KEYWORDS_HELP = [
    "subvención", "subvenciones", "ayuda", "ayudas", "convocatoria",
    "beca", "becas", "financiación", "préstamo", "crédito", "incentivo",
    "cofinanciación", "cofinancia", "fondo perdido", "grant",
]
KEYWORDS_COMPANY = [
    "empresa", "empresas", "pyme", "pymes", "autónomo", "autónomos",
    "emprendedor", "emprendedores", "startup", "empresarial",
    "industria", "industrial", "comercio", "negocio", "microempresa",
    "empleo", "contratación", "trabajador",
]
KEYWORDS_EXCLUDE = [
    "defunción", "matrimonio", "notificación", "resolución de recurso",
    "sanción", "multa", "expropiación",
]

# ── Dataclass ──────────────────────────────────────────────────────────────────

@dataclass
class Convocation:
    id: str
    title: str
    body: str
    bulletin: str
    community: str
    date: str
    url: str
    description: Optional[str] = None
    deadline: Optional[str] = None
    amount: Optional[str] = None
    sectors: list = field(default_factory=list)
    beneficiary_types: list = field(default_factory=list)
    relevance: float = 0.0
    scraping: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self):
        return asdict(self)

# ── Utilidades HTTP ────────────────────────────────────────────────────────────

def fetch_url(url: str, timeout: int = 15) -> Optional[str]:
    """Descarga una URL con reintentos y User-Agent de navegador."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "es-ES,es;q=0.9",
    }
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                encoding = resp.headers.get_content_charset() or "utf-8"
                return resp.read().decode(encoding, errors="ignore")
        except urllib.error.HTTPError as e:
            log.warning(f"HTTPError {e.code} en {url}")
            if e.code in (403, 404, 429, 503):
                return None
        except urllib.error.URLError as e:
            log.warning(f"URLError ({attempt+1}/3) en {url}: {e.reason}")
            time.sleep(2 ** attempt)
        except Exception as e:
            log.error(f"Error inesperado en {url}: {e}")
            time.sleep(2)
    return None

# ── Relevancia ─────────────────────────────────────────────────────────────────

def relevancy_score(text: str) -> float:
    """Puntuación 0-1 de relevancia empresarial.
    
    FIX: KEYWORDS_EXCLUDE resta en lugar de sumar.
    FIX: se usa presencia (bool) no conteo, para no disparar scores por repetición.
    """
    lower = text.lower()
    score = 0.0

    for kw in KEYWORDS_HELP:
        if kw in lower:
            score += 0.15

    for kw in KEYWORDS_COMPANY:
        if kw in lower:
            score += 0.10

    for kw in KEYWORDS_EXCLUDE:          # ← antes sumaba, ahora resta
        if kw in lower:
            score -= 0.30

    return max(0.0, min(1.0, score))

# ── ID único ───────────────────────────────────────────────────────────────────

def generate_id(bulletin: str, reference: str) -> str:
    return hashlib.md5(f"{bulletin}_{reference}".encode()).hexdigest()[:16]

# ── spaCy ──────────────────────────────────────────────────────────────────────

try:
    nlp = spacy.load("es_core_news_md", disable=["tagger", "parser", "lemmatizer"])
except OSError:
    log.warning(
        "Modelo spaCy 'es_core_news_md' no encontrado. "
        "Ejecuta: python -m spacy download es_core_news_md\n"
        "Usando extracción por regex como fallback."
    )
    nlp = None

# ── Extracción de importe ──────────────────────────────────────────────────────

def _extract_amount_spacy(text: str) -> Optional[str]:
    doc = nlp(text)
    candidates = []
    for ent in doc.ents:
        if ent.label_ in ("MONEY", "QUANTITY"):
            sent = ent.sent.text.lower()
            score = 0
            if any(w in sent for w in ("máximo", "hasta", "límite")):
                score += 3
            if any(w in sent for w in ("subvención", "ayuda", "financiación")):
                score += 2
            if "presupuesto" in sent:
                score -= 3
            if "total" in sent:
                score -= 2
            candidates.append((ent.text, score))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[1], reverse=True)
    return candidates[0][0]


def _extract_amount_regex(text: str) -> Optional[str]:
    patterns = [
        r"(\d[\d.,]*)\s*(?:millones?|M)\s*(?:de\s*)?(?:euros?|€)",
        r"(?:hasta|máximo|importe|límite)[^\d]{0,20}([\d.,]+)\s*(?:euros?|€)",
        r"([\d.,]+)\s*(?:euros?|€)",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return m.group(0).strip()
    return None


def _normalize_amount(raw: str) -> Optional[str]:
    try:
        is_million = bool(re.search(r"millón|millones|M\b", raw, re.I))
        cleaned = re.sub(r"[^\d.,]", "", raw)
        if cleaned.count(",") > cleaned.count("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
        value = float(cleaned) * (1_000_000 if is_million else 1)
        return f"{value:,.0f} €".replace(",", ".")
    except ValueError:
        return None


def extract_amount(text: str) -> Optional[str]:
    raw = _extract_amount_spacy(text) if nlp else _extract_amount_regex(text)
    if raw:
        return _normalize_amount(raw)
    return None

# ── Extracción de plazo ────────────────────────────────────────────────────────

def _extract_deadline_spacy(text: str) -> Optional[str]:
    doc = nlp(text)
    candidates = []
    for ent in doc.ents:
        if ent.label_ == "DATE":
            sent = ent.sent.text.lower()
            score = 0
            if any(w in sent for w in ("plazo", "solicitud")):
                score += 3
            if any(w in sent for w in ("presentación", "hasta")):
                score += 2
            if any(w in sent for w in ("finaliza", "finalizará")):
                score += 3
            if any(w in sent for w in ("publicación", "publicó")):
                score -= 3
            candidates.append((ent.text, score))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[1], reverse=True)
    return candidates[0][0]


def _extract_deadline_regex(text: str) -> Optional[str]:
    patterns = [
        r"hasta el (\d{1,2} de \w+ de \d{4})",
        r"plazo[^.]{0,80}(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
        r"(\d{1,2} de \w+ de \d{4})",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return m.group(0).strip()
    return None


def _normalize_deadline(raw: str) -> Optional[str]:
    try:
        return dateutil_parser.parse(raw, dayfirst=True).strftime("%Y-%m-%d")
    except (ValueError, OverflowError):
        return raw  # devolver el texto original si no se puede normalizar


def extract_deadline(text: str) -> Optional[str]:
    raw = _extract_deadline_spacy(text) if nlp else _extract_deadline_regex(text)
    if raw:
        return _normalize_deadline(raw)
    return None
