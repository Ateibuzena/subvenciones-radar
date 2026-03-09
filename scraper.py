#!/usr/bin/env python3
"""
====================================================
 MONITOR DE AYUDAS Y SUBVENCIONES PARA EMPRESAS
 Scraper: BOE + Boletines Autonómicos
====================================================
"""

import json
import re
import time
import logging
import hashlib
import urllib.request
import urllib.parse
import urllib.error
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path
from dataclasses import dataclass, asdict, field
from typing import Optional

# ── Configuración ────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s – %(message)s",
    handlers=[
        logging.FileHandler(DATA_DIR / "scraper.log"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("subvenciones")

# Palabras clave para filtrar ayudas/subvenciones empresariales
KEYWORDS_AYUDA = [
    "subvención", "subvenciones", "ayuda", "ayudas", "convocatoria",
    "beca", "becas", "financiación", "préstamo", "crédito", "incentivo",
    "cofinanciación", "cofinancia", "fondo perdido", "grant",
]
KEYWORDS_EMPRESA = [
    "empresa", "empresas", "pyme", "pymes", "autónomo", "autónomos",
    "emprendedor", "emprendedores", "startup", "empresarial",
    "industria", "industrial", "comercio", "negocio", "microempresa",
    "empleo", "contratación", "trabajador",
]
KEYWORDS_EXCLUIR = [
    "defunción", "matrimonio", "notificación", "resolución de recurso",
    "sanción", "multa", "expropiación",
]


# ── Dataclasses ───────────────────────────────────────────────────────────────
@dataclass
class Convocatoria:
    id: str
    titulo: str
    organismo: str
    boletin: str
    comunidad: str
    fecha_publicacion: str
    url: str
    descripcion: str = ""
    plazo_solicitud: str = ""
    importe_maximo: str = ""
    sectores: list = field(default_factory=list)
    tipo_beneficiario: list = field(default_factory=list)
    relevancia: float = 0.0
    fecha_scraping: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self):
        return asdict(self)


# ── Utilidades ────────────────────────────────────────────────────────────────
def fetch_url(url: str, timeout: int = 15) -> Optional[str]:
    """Descarga una URL con reintentos y User-Agent."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (compatible; SubvencionesBot/1.0; "
            "+https://github.com/subvenciones-monitor)"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml,*/*",
        "Accept-Language": "es-ES,es;q=0.9",
    }
    for intento in range(3):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                encoding = resp.headers.get_content_charset() or "utf-8"
                return resp.read().decode(encoding, errors="replace")
        except urllib.error.HTTPError as e:
            log.warning(f"HTTP {e.code} en {url}")
            if e.code in (403, 404):
                return None
        except urllib.error.URLError as e:
            log.warning(f"URL error ({intento+1}/3) {url}: {e.reason}")
            time.sleep(2 ** intento)
        except Exception as e:
            log.warning(f"Error inesperado {url}: {e}")
            time.sleep(2)
    return None


def calcular_relevancia(texto: str) -> float:
    """Puntuación 0-1 de relevancia para empresas."""
    texto_lower = texto.lower()
    score = 0.0
    for kw in KEYWORDS_AYUDA:
        if kw in texto_lower:
            score += 0.15
    for kw in KEYWORDS_EMPRESA:
        if kw in texto_lower:
            score += 0.10
    for kw in KEYWORDS_EXCLUIR:
        if kw in texto_lower:
            score -= 0.30
    return max(0.0, min(1.0, score))


def generar_id(boletin: str, referencia: str) -> str:
    return hashlib.md5(f"{boletin}:{referencia}".encode()).hexdigest()[:12]


def extraer_importe(texto: str) -> str:
    """Intenta extraer importes del texto."""
    patrones = [
        r"(\d[\d.,]*)[\s]*(?:millones?|M)[\s]*(?:de[\s]*)?(?:euros?|€)",
        r"(\d[\d.,]*)[\s]*(?:euros?|€)",
        r"(?:hasta|máximo|importe)[\s:]*(\d[\d.,]*)[\s]*(?:euros?|€)?",
    ]
    for pat in patrones:
        m = re.search(pat, texto, re.IGNORECASE)
        if m:
            return m.group(0).strip()
    return ""


def extraer_plazo(texto: str) -> str:
    """Intenta extraer plazos de solicitud."""
    patrones = [
        r"plazo[^.]{0,80}(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
        r"hasta el (\d{1,2} de \w+ de \d{4})",
        r"(\d{1,2} de \w+ de \d{4})",
    ]
    for pat in patrones:
        m = re.search(pat, texto, re.IGNORECASE)
        if m:
            return m.group(0).strip()
    return ""


# ── BOE (API JSON oficial) ────────────────────────────────────────────────────
class ScraperBOE:
    """
    Usa la API REST oficial del BOE:
    https://www.boe.es/datosabiertos/api/boe/sumario/{YYYYMMDD}
    """
    NOMBRE = "BOE"
    API_SUMARIO = "https://www.boe.es/datosabiertos/api/boe/sumario/{fecha}"
    API_DOCUMENTO = "https://www.boe.es/datosabiertos/api/boe/documento/{id}"
    URL_HTML = "https://www.boe.es/diario_boe/txt.php?id={id}"

    def __init__(self, dias_atras: int = 1):
        self.dias_atras = dias_atras

    def scrape(self) -> list[Convocatoria]:
        resultados = []
        for d in range(self.dias_atras):
            fecha = datetime.now() - timedelta(days=d)
            resultados.extend(self._scrape_dia(fecha))
        return resultados

    def _scrape_dia(self, fecha: datetime) -> list[Convocatoria]:
        fecha_str = fecha.strftime("%Y%m%d")
        url = self.API_SUMARIO.format(fecha=fecha_str)
        log.info(f"BOE: consultando sumario {fecha_str}")

        raw = fetch_url(url)
        if not raw:
            log.warning(f"BOE: no se pudo obtener sumario {fecha_str}")
            return []

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            log.error("BOE: JSON inválido")
            return []

        return self._parsear_sumario(data, fecha.strftime("%Y-%m-%d"))

    def _parsear_sumario(self, data: dict, fecha: str) -> list[Convocatoria]:
        resultados = []
        try:
            diario = data["data"]["sumario"]["diario"]
            secciones = diario if isinstance(diario, list) else [diario]
        except (KeyError, TypeError):
            return []

        for seccion in secciones:
            items = self._extraer_items(seccion)
            for item in items:
                conv = self._item_a_convocatoria(item, fecha)
                if conv:
                    resultados.append(conv)

        log.info(f"BOE {fecha}: {len(resultados)} convocatorias relevantes")
        return resultados

    def _extraer_items(self, nodo, items=None):
        """Recorre recursivamente el árbol JSON del sumario."""
        if items is None:
            items = []
        if isinstance(nodo, dict):
            if "titulo" in nodo and "identificador" in nodo:
                items.append(nodo)
            for v in nodo.values():
                self._extraer_items(v, items)
        elif isinstance(nodo, list):
            for elem in nodo:
                self._extraer_items(elem, items)
        return items

    def _item_a_convocatoria(self, item: dict, fecha: str) -> Optional[Convocatoria]:
        titulo = item.get("titulo", "")
        if not titulo:
            return None

        relevancia = calcular_relevancia(titulo)
        if relevancia < 0.15:
            return None

        id_doc = item.get("identificador", "")
        organismo = item.get("departamento", item.get("emisor", "Desconocido"))
        url = self.URL_HTML.format(id=id_doc)

        return Convocatoria(
            id=generar_id("BOE", id_doc),
            titulo=titulo,
            organismo=organismo,
            boletin="BOE",
            comunidad="Nacional",
            fecha_publicacion=fecha,
            url=url,
            importe_maximo=extraer_importe(titulo),
            plazo_solicitud=extraer_plazo(titulo),
            relevancia=relevancia,
        )


# ── Scraper RSS genérico ──────────────────────────────────────────────────────
class ScraperRSS:
    """Scraper genérico para boletines con feed RSS/Atom."""

    def __init__(self, nombre: str, comunidad: str, rss_url: str):
        self.nombre = nombre
        self.comunidad = comunidad
        self.rss_url = rss_url

    def scrape(self) -> list[Convocatoria]:
        log.info(f"{self.nombre}: consultando RSS")
        raw = fetch_url(self.rss_url)
        if not raw:
            log.warning(f"{self.nombre}: no se pudo obtener RSS")
            return []
        return self._parsear_rss(raw)

    def _parsear_rss(self, xml_str: str) -> list[Convocatoria]:
        resultados = []
        try:
            root = ET.fromstring(xml_str)
        except ET.ParseError as e:
            log.error(f"{self.nombre}: XML inválido: {e}")
            return []

        ns = {"atom": "http://www.w3.org/2005/Atom"}
        # Detectar formato RSS 2.0 o Atom
        items = root.findall(".//item") or root.findall(".//atom:entry", ns)

        for item in items:
            conv = self._item_a_convocatoria(item, ns)
            if conv:
                resultados.append(conv)

        log.info(f"{self.nombre}: {len(resultados)} convocatorias relevantes")
        return resultados

    def _get_text(self, elem, tag: str, ns: dict) -> str:
        node = elem.find(tag) or elem.find(f"atom:{tag}", ns)
        if node is not None and node.text:
            return node.text.strip()
        return ""

    def _item_a_convocatoria(self, item, ns: dict) -> Optional[Convocatoria]:
        titulo = self._get_text(item, "title", ns)
        descripcion = self._get_text(item, "description", ns) or \
                      self._get_text(item, "summary", ns)
        link = self._get_text(item, "link", ns)
        pub_date = self._get_text(item, "pubDate", ns) or \
                   self._get_text(item, "published", ns)

        texto_completo = f"{titulo} {descripcion}"
        relevancia = calcular_relevancia(texto_completo)
        if relevancia < 0.15:
            return None

        # Normalizar fecha
        try:
            for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d"):
                try:
                    fecha = datetime.strptime(pub_date[:25], fmt).strftime("%Y-%m-%d")
                    break
                except ValueError:
                    continue
            else:
                fecha = datetime.now().strftime("%Y-%m-%d")
        except Exception:
            fecha = datetime.now().strftime("%Y-%m-%d")

        # Limpiar HTML de descripción
        descripcion_limpia = re.sub(r"<[^>]+>", " ", descripcion)
        descripcion_limpia = re.sub(r"\s+", " ", descripcion_limpia).strip()[:500]

        return Convocatoria(
            id=generar_id(self.nombre, link or titulo),
            titulo=titulo,
            organismo=self.nombre,
            boletin=self.nombre,
            comunidad=self.comunidad,
            fecha_publicacion=fecha,
            url=link,
            descripcion=descripcion_limpia,
            importe_maximo=extraer_importe(texto_completo),
            plazo_solicitud=extraer_plazo(texto_completo),
            relevancia=relevancia,
        )


# ── Scrapers específicos autonómicos ──────────────────────────────────────────
class ScraperBOJA(ScraperRSS):
    """Boletín Oficial de la Junta de Andalucía."""
    def __init__(self):
        super().__init__(
            nombre="BOJA",
            comunidad="Andalucía",
            rss_url="https://www.juntadeandalucia.es/boja/rss/rss.xml",
        )


class ScraperDOGC(ScraperRSS):
    """Diari Oficial de la Generalitat de Catalunya."""
    def __init__(self):
        super().__init__(
            nombre="DOGC",
            comunidad="Cataluña",
            rss_url="https://portaldogc.gencat.cat/utilsEADOP/PDF/RSS/RSS_DOGC_RSSCA.xml",
        )


class ScraperBOCM(ScraperRSS):
    """Boletín Oficial de la Comunidad de Madrid."""
    def __init__(self):
        super().__init__(
            nombre="BOCM",
            comunidad="Madrid",
            rss_url="https://www.bocm.es/rss/bocm_rss.xml",
        )


class ScraperDOGV(ScraperRSS):
    """Diari Oficial de la Generalitat Valenciana."""
    def __init__(self):
        super().__init__(
            nombre="DOGV",
            comunidad="Comunitat Valenciana",
            rss_url="https://www.dogv.gva.es/portal/rss/es/rss.xml",
        )


class ScraperBOPV(ScraperRSS):
    """Boletín Oficial del País Vasco."""
    def __init__(self):
        super().__init__(
            nombre="BOPV",
            comunidad="País Vasco",
            rss_url="https://www.euskadi.eus/bopv2/datos/rss/bopv_es.xml",
        )


class ScraperBOE_BDNS:
    """
    Base de Datos Nacional de Subvenciones (BDNS) – API REST oficial.
    Fuente más completa y estructurada de convocatorias activas.
    https://www.infosubvenciones.es
    """
    NOMBRE = "BDNS"
    API_URL = (
        "https://www.infosubvenciones.es/bdnstrans/GE/es/convocatorias.json"
        "?tipoBeneficiario=2"  # 2 = Empresas/autónomos
        "&estado=1"            # 1 = Convocatorias abiertas
        "&numPagina=1"
        "&numRegistrosPagina=50"
    )

    def scrape(self) -> list[Convocatoria]:
        log.info("BDNS: consultando Base de Datos Nacional de Subvenciones")
        raw = fetch_url(self.API_URL)
        if not raw:
            log.warning("BDNS: no se pudo obtener respuesta")
            return []
        try:
            data = json.loads(raw)
            return self._parsear(data)
        except json.JSONDecodeError:
            log.error("BDNS: JSON inválido")
            return []

    def _parsear(self, data: dict) -> list[Convocatoria]:
        resultados = []
        convocatorias = data.get("convocatorias", data.get("data", []))
        if not isinstance(convocatorias, list):
            return []

        for item in convocatorias:
            titulo = item.get("descripcionConvocatoria", item.get("titulo", ""))
            organismo = item.get("nombreAdministracion", "")
            fecha = item.get("fechaRegistro", item.get("fechaPublicacion", ""))
            num_bdns = str(item.get("numConvocatoria", item.get("id", "")))
            importe = str(item.get("importeTotalConcedido", item.get("presupuesto", "")))
            url = (
                f"https://www.infosubvenciones.es/bdnstrans/GE/es/"
                f"convocatoria/{num_bdns}"
            )

            if not titulo:
                continue

            resultados.append(Convocatoria(
                id=generar_id("BDNS", num_bdns),
                titulo=titulo,
                organismo=organismo,
                boletin="BDNS",
                comunidad=item.get("comunidadAutonoma", "Nacional"),
                fecha_publicacion=fecha[:10] if fecha else "",
                url=url,
                importe_maximo=f"{importe} €" if importe and importe != "0" else "",
                plazo_solicitud=item.get("plazoSolicitudFin", ""),
                relevancia=0.9,  # BDNS ya filtra subvenciones
            ))

        log.info(f"BDNS: {len(resultados)} convocatorias")
        return resultados


# ── Gestor principal ──────────────────────────────────────────────────────────
class MonitorSubvenciones:
    """Orquesta todos los scrapers y persiste los resultados."""

    SCRAPERS = [
        ScraperBOE(dias_atras=3),
        ScraperBOE_BDNS(),
        ScraperBOJA(),
        ScraperDOGC(),
        ScraperBOCM(),
        ScraperDOGV(),
        ScraperBOPV(),
    ]

    DB_FILE = DATA_DIR / "convocatorias.json"
    ALERTAS_FILE = DATA_DIR / "alertas.json"

    def __init__(self):
        self.db = self._cargar_db()

    def _cargar_db(self) -> dict:
        if self.DB_FILE.exists():
            try:
                return json.loads(self.DB_FILE.read_text("utf-8"))
            except Exception:
                pass
        return {"convocatorias": {}, "ultima_actualizacion": None}

    def _guardar_db(self):
        self.db["ultima_actualizacion"] = datetime.now().isoformat()
        self.DB_FILE.write_text(
            json.dumps(self.db, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def ejecutar(self) -> dict:
        nuevas = []
        errores = []

        for scraper in self.SCRAPERS:
            nombre = getattr(scraper, "NOMBRE", getattr(scraper, "nombre", "?"))
            try:
                convocatorias = scraper.scrape()
                for conv in convocatorias:
                    if conv.id not in self.db["convocatorias"]:
                        self.db["convocatorias"][conv.id] = conv.to_dict()
                        nuevas.append(conv)
            except Exception as e:
                log.error(f"Error en scraper {nombre}: {e}")
                errores.append({"scraper": nombre, "error": str(e)})
            time.sleep(1)  # Respetar los servidores

        self._guardar_db()
        self._guardar_alertas(nuevas)

        resumen = {
            "fecha": datetime.now().isoformat(),
            "total_db": len(self.db["convocatorias"]),
            "nuevas_esta_ejecucion": len(nuevas),
            "errores": errores,
            "nuevas": [c.to_dict() for c in nuevas[:20]],
        }
        log.info(
            f"Ejecución completada: {len(nuevas)} nuevas, "
            f"{len(self.db['convocatorias'])} en DB total"
        )
        return resumen

    def _guardar_alertas(self, nuevas: list[Convocatoria]):
        alertas = []
        if self.ALERTAS_FILE.exists():
            try:
                alertas = json.loads(self.ALERTAS_FILE.read_text("utf-8"))
            except Exception:
                alertas = []

        for conv in nuevas:
            if conv.relevancia >= 0.5:
                alertas.append({
                    "fecha": datetime.now().isoformat(),
                    "convocatoria": conv.to_dict(),
                })

        # Mantener solo últimas 200 alertas
        alertas = alertas[-200:]
        self.ALERTAS_FILE.write_text(
            json.dumps(alertas, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def buscar(
        self,
        query: str = "",
        comunidad: str = "",
        boletin: str = "",
        desde: str = "",
        min_relevancia: float = 0.0,
    ) -> list[dict]:
        resultados = []
        query_lower = query.lower()

        for conv in self.db["convocatorias"].values():
            if comunidad and conv.get("comunidad", "") != comunidad:
                continue
            if boletin and conv.get("boletin", "") != boletin:
                continue
            if desde and conv.get("fecha_publicacion", "") < desde:
                continue
            if conv.get("relevancia", 0) < min_relevancia:
                continue
            if query_lower:
                haystack = (
                    f"{conv.get('titulo','')} {conv.get('descripcion','')} "
                    f"{conv.get('organismo','')}".lower()
                )
                if not all(w in haystack for w in query_lower.split()):
                    continue
            resultados.append(conv)

        return sorted(
            resultados,
            key=lambda x: (x.get("fecha_publicacion", ""), x.get("relevancia", 0)),
            reverse=True,
        )

    def estadisticas(self) -> dict:
        total = len(self.db["convocatorias"])
        por_boletin = {}
        por_comunidad = {}
        por_mes = {}

        for conv in self.db["convocatorias"].values():
            b = conv.get("boletin", "?")
            por_boletin[b] = por_boletin.get(b, 0) + 1
            c = conv.get("comunidad", "?")
            por_comunidad[c] = por_comunidad.get(c, 0) + 1
            fecha = conv.get("fecha_publicacion", "")
            mes = fecha[:7] if fecha else "?"
            por_mes[mes] = por_mes.get(mes, 0) + 1

        return {
            "total": total,
            "por_boletin": por_boletin,
            "por_comunidad": por_comunidad,
            "por_mes": dict(sorted(por_mes.items())[-6:]),
            "ultima_actualizacion": self.db.get("ultima_actualizacion"),
        }


# ── CLI ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    import argparse

    parser = argparse.ArgumentParser(
        description="Monitor de Ayudas y Subvenciones para Empresas"
    )
    subparsers = parser.add_subparsers(dest="comando")

    # scrape
    p_scrape = subparsers.add_parser("scrape", help="Ejecutar scrapers")
    p_scrape.add_argument("--dias", type=int, default=10, help="Días atrás en BOE")

    # buscar
    p_buscar = subparsers.add_parser("buscar", help="Buscar convocatorias")
    p_buscar.add_argument("query", nargs="?", default="", help="Texto a buscar")
    p_buscar.add_argument("--comunidad", default="")
    p_buscar.add_argument("--boletin", default="")
    p_buscar.add_argument("--desde", default="", help="Fecha inicio YYYY-MM-DD")
    p_buscar.add_argument("--relevancia", type=float, default=0.0)

    # stats
    subparsers.add_parser("stats", help="Mostrar estadísticas")

    args = parser.parse_args()
    monitor = MonitorSubvenciones()

    if args.comando == "scrape" or args.comando is None:
        print("🔍 Iniciando scrapers...")
        resumen = monitor.ejecutar()
        print(json.dumps(resumen, ensure_ascii=False, indent=2))

    elif args.comando == "buscar":
        resultados = monitor.buscar(
            query=args.query,
            comunidad=args.comunidad,
            boletin=args.boletin,
            desde=args.desde,
            min_relevancia=args.relevancia,
        )
        print(f"\n📋 {len(resultados)} convocatorias encontradas:\n")
        for r in resultados[:20]:
            print(f"  [{r['boletin']}] {r['fecha_publicacion']} – {r['titulo'][:80]}")
            print(f"       {r['url']}\n")

    elif args.comando == "stats":
        stats = monitor.estadisticas()
        print(json.dumps(stats, ensure_ascii=False, indent=2))
