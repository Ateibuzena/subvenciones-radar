"""
====================================================
 MONITOR DE AYUDAS Y SUBVENCIONES PARA EMPRESAS
 Scraper: BOE + Boletines Autonómicos
====================================================
"""

import json # Para manejar archivos JSON
import re   # Para expresiones regulares
import time # Para manejar tiempos y retrasos
from datetime import datetime, timedelta # Para manejar fechas y tiempos
from pathlib import Path # Para manejar rutas de archivos
from dataclasses import dataclass, asdict, field # Para definir clases de datos
import logging # Para registrar eventos y errores
import hashlib # Para generar hashes únicos
import urllib.request # Para realizar solicitudes HTTP
import urllib.parse # Para manejar URLs
import urllib.error # Para manejar errores HTTP
import xml.etree.ElementTree as ET # Para parsear XML
from typing import Optional # Para anotaciones de tipos

import spacy # Para procesamiento de lenguaje natural y extracción de información

# Configuración

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

# Configuración de logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s", # Formato de los mensajes de log
    handlers=[
        logging.FileHandler(BASE_DIR / "scraper.log"), # Guardar logs en un archivo
        logging.StreamHandler() # Mostrar logs en la consola
    ]
)

log = logging.getLogger("subvenciones") # Logger específico para el scraper

# Palabras clave para filtrar ayudas/subvenciones empresariales

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

# Definición de la clase de datos para una ayuda/subvención

@dataclass
class Convocation:
    id: str # ID único generado a partir del título y la fecha
    title: str # Título de la convocatoria
    body: str # Organismo que publica la convocatoria
    bulletin: str # Boletín donde se publica la convocatoria (BOE o boletín autonómico)
    community: str # Comunidad autónoma a la que se dirige la convocatoria
    date: str # Fecha de publicación de la convocatoria
    url: str # URL de la convocatoria
    description: Optional[str] = None # Descripción o resumen de la convocatoria
    deadline: Optional[str] = None # Plazo para presentar solicitudes
    amount: Optional[str] = None # Importe máximo de la ayuda/subvención
    sectors: list = field(default_factory=list) # Lista de sectores beneficiarios
    beneficiary_types: list = field(default_factory=list) # Lista de tipos de beneficiarios (empresa, autónomo, etc.)
    relevance: float = 0.0 # Puntuación de relevancia basada en palabras clave
    scraping: str = field(default_factory=lambda: datetime.now().isoformat()) # Fecha y hora del scraping

    def to_dict(self): # Método para convertir la instancia a un diccionario
        return asdict(self) # Convertir la instancia a un diccionario para facilitar su almacenamiento en JSON

# Funciones auxiliares

def fetch_url(url: str, timeout: int = 15) -> Optional[str]:
    """ Realiza una solicitud HTTP GET a la URL especificada
    con reintentos y manejo de errores. Descarga la información
    de la convocatoria. """
    headers = {
        #"User-Agent": (
        #    "Mozilla/5.0 (compatible; SubvencionesBot/1.0; "
        #    "+https://github.com/subvenciones-monitor)"
        #), // User-Agent personalizado para identificar el scraper
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36", # User-Agent para simular un navegador
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8", # Aceptar varios tipos de contenido
        "Accept-Language": "es-ES,es;q=0.9", # Aceptar contenido en español
    }   
    for tried in range(3): # Intentar hasta 3 veces en caso de error

        try:
            request = urllib.request.Request(url, headers=headers) # Crear la solicitud con los encabezados personalizados

            with urllib.request.urlopen(request, timeout=timeout) as response: # Abrir la URL
                encoding = response.headers.get_content_charset() or "utf-8" # Obtener la codificación del contenido
                return response.read().decode(encoding, errors="ignore") # Devolver el contenido decodificado

        except urllib.error.HTTPError as e:
            log.warning(f"HTTPError {e.code} al acceder a {url}: {e.reason}") # Registrar errores HTTP

            if e.code in [429, 503]: # Si el error es de tipo "Too Many Requests" o "Service Unavailable"
                return None # No reintentar, ya que el servidor está indicando que no puede manejar la solicitud en este momento

        except urllib.error.URLError as e:
            log.warning(f"URLError al acceder a {url}: {e.reason}") # Registrar errores de URL
            time.sleep(2 ** tried) # Esperar un tiempo exponencial antes de reintentar
        
        except Exception as e:
            log.error(f"Error inesperado al acceder a {url}: {str(e)}") # Registrar cualquier otro error inesperado
            time.sleep(2 ** tried) # Esperar un tiempo exponencial antes de reintentar
            
    log.error(f"No se pudo acceder a {url} después de 3 intentos") # Registrar el fallo después de 3 intentos
    return None # Devolver None si no se pudo acceder a la URL después de los intentos     

def relevancy_score(text: str) -> float:
    """ Calcula una puntuación  del 0-1 de relevancia basada en la presencia
    de palabras clave en el texto. """
    
    lower_text = text.lower() # Convertir el texto a minúsculas para facilitar la búsqueda de palabras clave
    score = 0.0 # Inicializar la puntuación de relevancia

    for kw in KEYWORDS_HELP: # Contar cuántas palabras clave de ayuda aparecen en el texto
        score += lower_text.count(kw) * 0.15
    
    for kw in KEYWORDS_COMPANY: # Contar cuántas palabras clave de empresa aparecen en el texto
        score += lower_text.count(kw) * 0.15

    for kw in KEYWORDS_EXCLUDE: # Contar cuántas palabras clave de exclusión aparecen en el texto
        score += lower_text.count(kw) * 0.15
    
    return max(0.0, min(1.0, score)) # Asegurar que la puntuación esté entre 0 y 1

def generate_id(bulletin: str, reference: str) -> str:
    """ Genera un ID único a partir del boletín y la referencia utilizando SHA-256 """
    #return hashlib.md5(f"{boletin}:{referencia}".encode()).hexdigest()[:12] # Generar un ID único a partir del boletín y la referencia utilizando MD5 (recortado a 12 caracteres)
    return hashlib.md5(f"{bulletin}_{reference}".encode()).hexdigest()[:16] # Generar un ID único a partir del boletín y la referencia utilizando SHA-256

nlp = spacy.load(
    "es_core_news_md",
    disable=["tagger", "parser", "lemmatizer"]
) # Cargar el modelo de spaCy para español, deshabilitando componentes innecesarios para mejorar el rendimiento

def extract_import(text: str) -> Optional[str]:
    """ Extrae el importe máximo de la ayuda/subvención del texto utilizando spaCy para identificar entidades monetarias """
    
    doc = nlp(text)

    candidates = []

    for ent in doc.ents: # Iterar sobre las entidades reconocidas por spaCy
        if ent.label_ in ["MONEY", "QUANTITY"]: # Filtrar solo las entidades que son de tipo dinero o cantidad
            sentence = ent.sent.text.lower() # Obtener la oración completa donde se encuentra la entidad y convertirla a minúsculas

            score = 0;

            if ("máximo" in sentence
                or "hasta" in sentence
                or "límite" in sentence): # Aumentar la puntuación si la oración indica un límite o cantidad máxima
                score += 3

            if ("subvención" in sentence
                or "ayuda" in sentence
                or "financiación" in sentence): # Aumentar la puntuación si la oración menciona una subvención, ayuda o financiación
                score += 2

            if "presupuesto" in sentence:
                score -= 3 # Disminuir la puntuación si la oración menciona un presupuesto, ya que esto puede indicar el presupuesto total de la convocatoria en lugar del importe máximo por beneficiario

            if "total" in sentence:
                score -= 2 # Disminuir la puntuación si la oración menciona un total, ya que esto también puede indicar el presupuesto total de la convocatoria

            candidates.append((ent.text, score)) # Agregar la entidad y su puntuación a la lista de candidatos

    if not candidates:
        return None # Devolver None si no se encontraron entidades monetarias

    # Ordenar los candidatos por puntuación y devolver el que tenga la puntuación más alta
    candidates.sort(key=lambda x: x[1], reverse=True) # Ordenar los candidatos por puntuación de mayor a menor
    best_candidate = candidates[0][0] # Obtener el texto de la entidad con la puntuación más alta
    return best_candidate # Devolver el importe encontrado como el candidato más relevante según el análisis de spaCy

def normalize_amount(amount_str: str) -> Optional[str]:
    """ Normaliza el importe encontrado a un formato estándar con punto decimal y símbolo de euro """
    try:
        if ("millón" in amount_str.lower() or "m " in amount_str.lower()):
            amount_str = re.sub(r"(?i)(millón|m)\s*", "", amount_str) # Eliminar la palabra "millón" o "M" si está presente, ya que esto indica que el importe está en millones
            multiplier = 1_000_000 # Establecer el multiplicador a 1 millón para convertir el importe a su valor real
        else:
            multiplier = 1 # Si no se menciona "millón", el multiplicador es 1 (el importe ya está en su valor real)
        # Eliminar espacios y símbolos no numéricos, excepto puntos y comas
        cleaned = re.sub(r"[^\d.,]", "", amount_str)
        # Reemplazar comas por puntos si es necesario
        if cleaned.count(",") > cleaned.count("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
        # Convertir a float para validar el formato
        value = float(cleaned)
        return f"{value * multiplier:.2f} €" # Devolver el importe formateado con dos decimales y símbolo de euro
    except ValueError:
        return None # Devolver None si no se pudo convertir el importe a un número válido

def extract_amount(text: str) -> Optional[str]:
    """ Extrae el importe máximo de la ayuda/subvención del texto utilizando spaCy y normaliza el resultado """
    raw_amount = extract_import(text) # Extraer el importe utilizando spaCy
    if raw_amount:
        return normalize_amount(raw_amount) # Normalizar el importe extraído a un formato estándar
    return None # Devolver None si no se encontró ningún importe en el texto

def extract_date(text: str) -> Optional[str]:
    """ Extrae la fecha límite de presentación de solicitudes del texto utilizando spaCy para identificar entidades de fecha """
    
    doc = nlp(text)

    candidates = []

    for ent in doc.ents: # Iterar sobre las entidades reconocidas por spaCy
        if ent.label_ in ["DATE"]: # Filtrar solo las entidades que son de tipo fecha
            sentence = ent.sent.text.lower() # Obtener la oración completa donde se encuentra la entidad y convertirla a minúsculas

            score = 0;

            if ("plazo" in sentence
                or "solicitud" in sentence):
                score += 3
        
            if ("presentación" in sentence
                or "hasta" in sentence):
                score += 2

            if ("finaliza" in sentence
                or "finalizará" in sentence):
                score += 3

            if ("publicación" in sentence
                or "publicó" in sentence):
                score -= 3

            candidates.append((ent.text, score)) # Agregar la entidad y su puntuación a la lista de candidatos

    if not candidates:
        return None # Devolver None si no se encontraron entidades de fecha

    # Ordenar los candidatos por puntuación y devolver el que tenga la puntuación más alta
    candidates.sort(key=lambda x: x[1], reverse=True) # Ordenar los candidatos por puntuación de mayor a menor
    best_candidate = candidates[0][0] # Obtener el texto de la entidad con la puntuación más alta
    return best_candidate # Devolver la fecha encontrada como el candidato más relevante según el análisis de spaCy

from dateutil import parser

def normalize_date(date_str: str) -> Optional[str]:
    """ Normaliza la fecha encontrada a un formato estándar ISO 8601 (YYYY-MM-DD) """
    try:
        parsed_date = parser.parse(date_str, dayfirst=True) # Analizar la fecha utilizando dateutil, asumiendo formato día/mes/año
        return parsed_date.strftime("%Y-%m-%d") # Devolver la fecha formateada en formato ISO 8601
    except (ValueError, OverflowError):
        return None # Devolver None si no se pudo analizar la fecha correctamente

def extract_deadline(text: str) -> Optional[str]:
    """ Extrae la fecha límite de presentación de solicitudes del texto utilizando spaCy y normaliza el resultado """
    raw_date = extract_date(text) # Extraer la fecha utilizando spaCy
    if raw_date:
        return normalize_date(raw_date) # Normalizar la fecha extraída a un formato estándar
    return None # Devolver None si no se encontró ninguna fecha límite en el texto

#def extract_deadline(text: str) -> Optional[str]:
#    """ Extrae la fecha límite de presentación de solicitudes del texto utilizando expresiones regulares """
#    patterns = [
#        r"fecha límite de presentación\s*[:\-]?\s*(\d{1,2}\s+\w+\s+\d{4})", # Buscar frases que indiquen la fecha límite de presentación
#        r"plazo para presentar solicitudes\s*[:\-]?\s*(\d{1,2}\s+\w+\s+\d{4})", # Buscar frases que indiquen el plazo para presentar solicitudes
#        r"hasta el\s*[:\-]?\s*(\d{1,2}\s+\w+\s+\d{4})", # Buscar frases que indiquen una fecha límite con "hasta el"
#        r"fecha de cierre\s*[:\-]?\s*(\d{1,2}\s+\w+\s+\d{4})", # Buscar frases que indiquen la fecha de cierre
#    ]
#    for pattern in patterns:
#        match = re.search(pattern, text, re.IGNORECASE) # Buscar el patrón en el texto sin importar mayúsculas o minúsculas
#        if match:
#            return match.group(1) # Devolver la fecha encontrada en formato día mes año
#
#    return None # Devolver None si no se encontró ninguna fecha límite en el texto

#def extract_import(text: str) -> Optional[str]:
#    """ Extrae el importe máximo de la ayuda/subvención del texto utilizando expresiones regulares """
#    
#    patterns = [
#        r"importe máximo de\s*[:\-]?\s*([\d\.,]+)\s*(€|euros)?", # Buscar frases que indiquen el importe máximo
#        r"subvención de\s*[:\-]?\s*([\d\.,]+)\s*(€|euros)?", # Buscar frases que indiquen una subvención específica
#        r"ayuda de\s*[:\-]?\s*([\d\.,]+)\s*(€|euros)?", # Buscar frases que indiquen una ayuda específica
#        r"financiación de\s*[:\-]?\s*([\d\.,]+)\s*(€|euros)?", # Buscar frases que indiquen una financiación específica
#        r"(?:hasta|máximo|límite|cantidad|importe)\s*[:\-]?\s*([\d\.,]+)\s*(€|euros)?", # Buscar frases que indiquen un límite o cantidad máxima
#        r"(\d[\d.,]*)[\s]*(?:millones?|M)[\s]*(?:de[\s]*)?(?:euros?|€)",
#        r"(\d[\d.,]*)[\s]*(?:euros?|€)",
#    ]
#    for pattern in patterns:
#        match = re.search(pattern, text, re.IGNORECASE) # Buscar el patrón en el texto sin importar mayúsculas o minúsculas
#        if match:
#            return match.group(1).replace(".", "").replace(",", ".") + " €" # Devolver el importe encontrado, formateado como número con punto decimal y símbolo de euro
#
#    return None # Devolver None si no se encontró ningún importe en el texto
