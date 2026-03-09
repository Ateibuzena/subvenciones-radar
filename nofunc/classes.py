from __future__ import annotations
from typing import Optional, List
from datetime import datetime, timedelta
from html import unescape
from urllib.parse import urljoin
import json
import re
import xml.etree.ElementTree as ET
import logging as log
# classes.py
from scripts.scraper import Convocation, fetch_url, relevancy_score, generate_id, extract_amount, extract_deadline
# BOE (API JSON oficial)
class BOEScraper:
    """
    Usa la API REST oficial del BOE:
    https://www.boe.es/datosabiertos/api/boe/sumario/{YYYYMMDD}
    """

    NAME = "BOE" # Nombre del boletín para identificar la fuente de las convocatorias
    API_SUMARIO = "https://www.boe.es/datosabiertos/api/boe/sumario/{fecha}"
    API_DOC = "https://www.boe.es/datosabiertos/api/boe/documento/{id}"
    URL_HTML = "https://www.boe.es/diario_boe/txt.php?id={id}"

    def __init__(self, days_back: int = 1):
        self.days_back = days_back # Número de días hacia atrás para buscar convocatorias recientes
    
    def scrape(self) -> list:
        """ Realiza el scraping de convocatorias del BOE utilizando la API oficial y devuelve una lista de objetos Convocation """
        results = [] # Lista para almacenar las convocatorias encontradas

        for d in range(self.days_back): # Iterar sobre los días hacia atrás
            date = "20260228" # Calcular la fecha en formato YYYYMMDD

            print(f"\n\n\n\n\n\nFECHA: {date}\n\n\n\n\n\n")

            url = self.API_SUMARIO.format(fecha=date) # Construir la URL de la API para el sumario del día
            log.info(f"Consultando BOE para fecha {date}...") # Registrar la consulta al BOE

            response = fetch_url(url) # Realizar la solicitud a la API del BOE
            if not response:
                log.warning(f"No se pudo obtener el sumario del BOE para {date}") # Registrar si no se pudo obtener el sumario
                continue
            
            try:
                data = json.loads(response) # Parsear la respuesta JSON de la API
            except json.JSONDecodeError as e:
                log.error(f"Error al parsear JSON del BOE para {date}: {str(e)}") # Registrar errores al parsear el JSON
                continue

            results.extend(self._parse_summary(data, date)) # Analizar el sumario y agregar las convocatorias encontradas a los resultados
        
        return results # Devolver la lista de convocatorias encontradas

    def _parse_summary(self, data: dict, date: str) -> list:
        """ Analiza el sumario del BOE y devuelve una lista de objetos Convocation para las convocatorias relevantes """
        results = [] # Lista para almacenar las convocatorias encontradas en el sumario

        try:
            diario = data["data"]["sumario"]["diario"] # Obtener el nombre del diario del sumario
        except KeyError:
            log.error(f"Estructura de datos inesperada en el sumario del BOE para {date}") # Registrar si la estructura de datos no es la esperada
            return results
        
        items = self._extract_items(diario) # Extraer los items del sumario, que contienen la información de cada convocatoria

        for item in items: # Iterar sobre los items extraídos del sumario
            title = item.get("titulo", "") # Obtener el título de la convocatoria
            if not title:
                continue # Si no hay título, saltar esta convocatoria
            
            doc_id = item.get("identificador") # Obtener el ID del documento para construir la URL
            if not doc_id:
                continue

            text = self._fetch_document_text(doc_id) # Obtener el texto completo del documento utilizando su ID
            if not text:
                log.warning(f"No se pudo obtener el texto del documento {doc_id} para la convocatoria '{title}'") # Registrar si no se pudo obtener el texto del documento
                continue
            
            full_text = f"{title}\n{text[:1500]}" # Combinar el título y el texto completo para un análisis de relevancia más preciso

            relevance = relevancy_score(full_text) # Calcular la puntuación de relevancia basada solo en el título inicialmente
            if relevance < 0.3: # Filtrar convocatorias que no sean mínimamente relevantes basándose en el título
                continue

            amount = extract_amount(full_text) # Intentar extraer el importe máximo de la ayuda/subvención del texto completo
            deadline = extract_deadline(full_text) # Intentar extraer la fecha límite de presentación

            convocation = Convocation( # Crear un objeto Convocation con la información extraída
                id=generate_id("BOE", doc_id), # Generar un ID único para la convocatoria
                title=title,
                body=item.get("departamento", "BOE"),
                bulletin="BOE",
                community=self._extract_community(text), # Extraer la comunidad autónoma a partir del cuerpo de la convocatoria
                date=date,
                url=self.URL_HTML.format(id=doc_id), # Construir la URL de la convocatoria utilizando su ID
                amount=amount,
                deadline=deadline,
                relevance=relevance,
            )

            results.append(convocation) # Agregar la convocatoria a los resultados

        return results # Devolver la lista de convocatorias encontradas en el sumario

    def _fetch_document_text(self, doc_id: str) -> Optional[str]:
        """ Obtiene el texto completo del documento del BOE utilizando su ID a través de la API oficial """
        url = self.API_DOC.format(id=doc_id) # Construir la URL de la API para obtener el documento completo

        response = fetch_url(url) # Realizar la solicitud a la API del BOE
        if not response:
            return None # Devolver None si no se pudo obtener el documento
        
        # Intentar parsear como XML
        try:
            root = ET.fromstring(response)
            return root, "xml"
        except ET.ParseError:
            log.warning("Respuesta no parseable, se devuelve crudo")
            return response, "raw"

    def _extract_items(self, node: dict, items=None) -> list:
        """ Extrae los items del sumario del BOE, que contienen la información de cada convocatoria """
        if items is None:
            items = [] # Lista para almacenar los items extraídos

        if isinstance(node, dict):
            if "titulo" in node and "identificador" in node: # Verificar si el nodo actual tiene un título e identificador, lo que indica que es un item relevante
                items.append(node) # Agregar el item encontrado en el nodo actual
            for value in node.values():
                self._extract_items(value, items) # Recursivamente buscar items en los nodos hijos
        elif isinstance(node, list):
            for element in node:
                self._extract_items(element, items) # Recursivamente buscar items en los elementos de la lista
        return items # Devolver la lista de items extraídos

    @staticmethod
    def _extract_community(text: str) -> str:
        """Heurística simple para etiquetar comunidad cuando no hay metadato explícito."""
        text_l = (text or "").lower()
        communities = {
            "andaluc": "Andalucía",
            "catalu": "Cataluña",
            "madrid": "Madrid",
            "valenc": "Comunitat Valenciana",
            "eusk": "País Vasco",
            "vasco": "País Vasco",
            "galicia": "Galicia",
            "castilla": "Castilla y León",
            "extremadura": "Extremadura",
            "arag": "Aragón",
        }
        for token, label in communities.items():
            if token in text_l:
                return label
        return "Nacional"

# RSS Scraper genérico para boletines con feed RSS
class RSSScraper:
    """
    Scraper genérico para boletines con feed RSS o Atom.
    Descarga el feed, extrae items y analiza el contenido del enlace.
    """

    def __init__(self, name: str, community: str, rss_url: str):
        self.name = name
        self.community = community
        self.rss_url = rss_url

    def scrape(self) -> list[Convocation]:
        log.info(f"{self.name}: consultando RSS")

        raw = fetch_url(self.rss_url)
        if not raw:
            log.warning(f"{self.name}: no se pudo obtener RSS")
            return []

        return self._parse_feed(raw)

    def _parse_feed(self, xml_str: str) -> list[Convocation]:

        try:
            root = ET.fromstring(xml_str)
        except ET.ParseError as e:
            log.warning(f"{self.name}: no es XML RSS/Atom ({e}), probando parser HTML")
            return self._parse_html_listing(xml_str)

        ns = {"atom": "http://www.w3.org/2005/Atom"}

        items = root.findall(".//item") or root.findall(".//atom:entry", ns)

        results = []

        for item in items:
            conv = self._item_to_convocation(item, ns)
            if conv:
                results.append(conv)

        log.info(f"{self.name}: {len(results)} convocatorias relevantes")

        return results

    def _get_text(self, elem, tag: str, ns: dict) -> str:

        node = elem.find(tag) or elem.find(f"atom:{tag}", ns)

        if node is None:
            return ""

        text = (node.text or "").strip()

        # En Atom, <link> suele venir como atributo href y no como texto interno.
        if not text and tag == "link":
            text = (node.attrib.get("href") or "").strip()

        return text

    def _item_to_convocation(self, item, ns) -> Optional[Convocation]:

        title = self._get_text(item, "title", ns)
        link = self._get_text(item, "link", ns)

        if not title:
            return None

        description = (
            self._get_text(item, "description", ns)
            or self._get_text(item, "summary", ns)
        )

        pub_date = (
            self._get_text(item, "pubDate", ns)
            or self._get_text(item, "published", ns)
        )

        date = self._normalize_date(pub_date)

        # descargar contenido real del boletín
        article_text = fetch_url(link) if link else ""

        combined_text = f"{title}\n{description}\n{article_text[:1500]}"

        relevance = relevancy_score(combined_text)

        if relevance < 0.3:
            return None

        amount = extract_amount(combined_text)
        deadline = extract_deadline(combined_text)

        description_clean = re.sub(r"<[^>]+>", " ", description)
        description_clean = re.sub(r"\s+", " ", description_clean).strip()[:400]

        return Convocation(
            id=generate_id(self.name, link or title),
            title=title,
            body=self.name,
            bulletin=self.name,
            community=self.community,
            date=date,
            url=link,
            description=description_clean,
            amount=amount,
            deadline=deadline,
            relevance=relevance,
        )

    def _parse_html_listing(self, html: str) -> list[Convocation]:
        """Fallback para portales que ya no exponen RSS público y publican HTML."""
        anchors = re.findall(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html, re.I | re.S)
        results: list[Convocation] = []

        for href, raw_label in anchors:
            label = re.sub(r"<[^>]+>", " ", raw_label)
            label = unescape(re.sub(r"\s+", " ", label)).strip()
            if len(label) < 40:
                continue

            full_url = urljoin(self.rss_url, href)
            relevance = relevancy_score(label)
            if relevance < 0.3:
                continue

            results.append(
                Convocation(
                    id=generate_id(self.name, full_url or label),
                    title=label[:240],
                    body=self.name,
                    bulletin=self.name,
                    community=self.community,
                    date=datetime.now().strftime("%Y-%m-%d"),
                    url=full_url,
                    description=label[:400],
                    relevance=relevance,
                )
            )

            if len(results) >= 100:
                break

        log.info(f"{self.name}: {len(results)} convocatorias relevantes (fallback HTML)")
        return results

    def _normalize_date(self, pub_date: str) -> str:

        if not pub_date:
            return datetime.now().strftime("%Y-%m-%d")

        formats = [
            "%a, %d %b %Y %H:%M:%S %z",
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%d",
        ]

        for fmt in formats:
            try:
                return datetime.strptime(pub_date[:30], fmt).strftime("%Y-%m-%d")
            except ValueError:
                continue

        return datetime.now().strftime("%Y-%m-%d")

# Scrapers autonómicos

class BOJAScraper(RSSScraper):
    def __init__(self):
        super().__init__(
            name="BOJA",
            community="Andalucía",
            rss_url="https://www.juntadeandalucia.es/boja.html",
        )


class DOGCScraper(RSSScraper):
    def __init__(self):
        super().__init__(
            name="DOGC",
            community="Cataluña",
            rss_url="https://dogc.gencat.cat/ca/inici/",
        )


class BOCMScraper(RSSScraper):
    def __init__(self):
        super().__init__(
            name="BOCM",
            community="Madrid",
            rss_url="https://www.bocm.es/sumarios.rss",
        )


class DOGVScraper(RSSScraper):
    def __init__(self):
        super().__init__(
            name="DOGV",
            community="Comunitat Valenciana",
            rss_url="https://dogv.gva.es/es",
        )


class BOPVScraper(RSSScraper):
    def __init__(self):
        super().__init__(
            name="BOPV",
            community="País Vasco",
            rss_url="https://www.euskadi.eus/web01-bopv/es/bopv2/datos/Ultimo.shtml",
        )

# BDNS (API JSON oficial)

class BDNSScraper:

    NAME = "BDNS"

    API_URL = (
        "https://www.infosubvenciones.es/bdnstrans/GE/es/convocatorias.json"
        "?tipoBeneficiario=2"
        "&estado=1"
        "&numPagina=1"
        "&numRegistrosPagina=50"
    )

    def scrape(self) -> list[Convocation]:

        log.info("BDNS: consultando convocatorias")

        raw = fetch_url(self.API_URL)

        if not raw:
            return []

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            log.error("BDNS: JSON inválido")
            return []

        return self._parse(data)

    def _parse(self, data) -> list[Convocation]:

        results = []

        items = data.get("convocatorias", [])

        for item in items:

            title = item.get("descripcionConvocatoria") or item.get("titulo")

            if not title:
                continue

            ref = str(item.get("numConvocatoria"))

            url = f"https://www.infosubvenciones.es/bdnstrans/GE/es/convocatoria/{ref}"

            amount = item.get("importeTotalConcedido")

            results.append(
                Convocation(
                    id=generate_id("BDNS", ref),
                    title=title,
                    body=item.get("nombreAdministracion", ""),
                    bulletin="BDNS",
                    community=item.get("comunidadAutonoma", "Nacional"),
                    date=(item.get("fechaPublicacion") or "")[:10],
                    url=url,
                    amount=f"{amount} €" if amount else None,
                    deadline=item.get("plazoSolicitudFin"),
                    relevance=0.95,
                )
            )

        log.info(f"BDNS: {len(results)} convocatorias")

        return results