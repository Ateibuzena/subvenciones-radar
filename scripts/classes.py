from __future__ import annotations

from typing import Optional
from datetime import datetime, timedelta
from html import unescape
from urllib.parse import urljoin
import json
import re
import xml.etree.ElementTree as ET
import logging as log

from scripts.scraper import (
    Convocation, fetch_url, relevancy_score, generate_id,
    extract_amount, extract_deadline,
)


# ── BOE ───────────────────────────────────────────────────────────────────────

class BOEScraper:
    """
    Usa la API REST oficial del BOE:
    https://www.boe.es/datosabiertos/api/boe/sumario/{YYYYMMDD}
    """

    NAME = "BOE"
    API_SUMARIO = "https://www.boe.es/datosabiertos/api/boe/sumario/{fecha}"
    API_DOC     = "https://www.boe.es/datosabiertos/api/boe/documento/{id}"
    URL_HTML    = "https://www.boe.es/diario_boe/txt.php?id={id}"

    def __init__(self, days_back: int = 3):
        self.days_back = days_back

    def scrape(self) -> list[Convocation]:
        results = []
        for d in range(self.days_back):
            # FIX: fecha dinámica, no hardcodeada
            date_obj = datetime.now() - timedelta(days=d)
            # El BOE no publica en fin de semana; saltarlos evita peticiones vacías
            if date_obj.weekday() >= 5:
                continue
            date_str = date_obj.strftime("%Y%m%d")
            results.extend(self._scrape_day(date_str))
        return results

    def _scrape_day(self, date_str: str) -> list[Convocation]:
        url = self.API_SUMARIO.format(fecha=date_str)
        log.info(f"BOE: consultando sumario {date_str}")

        response = fetch_url(url)
        if not response:
            log.warning(f"BOE: sin respuesta para {date_str}")
            return []

        try:
            data = json.loads(response)
        except json.JSONDecodeError as e:
            log.error(f"BOE: JSON inválido para {date_str}: {e}")
            return []

        return self._parse_summary(data, date_str)

    def _parse_summary(self, data: dict, date_str: str) -> list[Convocation]:
        results = []

        try:
            diario = data["data"]["sumario"]["diario"]
        except (KeyError, TypeError):
            log.error(f"BOE: estructura inesperada en {date_str}")
            return results

        items = self._extract_items(diario)
        date_iso = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"

        for item in items:
            title = item.get("titulo", "")
            doc_id = item.get("identificador", "")
            if not title or not doc_id:
                continue

            # Filtro rápido por título antes de descargar el documento completo
            if relevancy_score(title) < 0.15:
                continue

            # FIX: _fetch_document_text ahora devuelve str, no tupla
            text = self._fetch_document_text(doc_id) or ""
            full_text = f"{title}\n{text[:2000]}"

            relevance = relevancy_score(full_text)
            if relevance < 0.3:
                continue

            results.append(Convocation(
                id=generate_id("BOE", doc_id),
                title=title,
                body=item.get("departamento", "BOE"),
                bulletin="BOE",
                community=self._extract_community(text),
                date=date_iso,
                url=self.URL_HTML.format(id=doc_id),
                amount=extract_amount(full_text),
                deadline=extract_deadline(full_text),
                relevance=relevance,
            ))

        log.info(f"BOE {date_str}: {len(results)} convocatorias relevantes")
        return results

    def _fetch_document_text(self, doc_id: str) -> Optional[str]:
        """
        FIX: antes devolvía (root, "xml") o (response, "raw") — una tupla.
        Ahora siempre devuelve str o None.
        """
        url = self.API_DOC.format(id=doc_id)
        response = fetch_url(url)
        if not response:
            return None

        # Intentar extraer texto de XML
        try:
            root = ET.fromstring(response)
            # Concatenar todo el texto de los nodos
            return " ".join(root.itertext())
        except ET.ParseError:
            # Si no es XML válido, devolver el texto crudo
            return response

    def _extract_items(self, node, items=None) -> list:
        if items is None:
            items = []
        if isinstance(node, dict):
            if "titulo" in node and "identificador" in node:
                items.append(node)
            for value in node.values():
                self._extract_items(value, items)
        elif isinstance(node, list):
            for element in node:
                self._extract_items(element, items)
        return items

    @staticmethod
    def _extract_community(text: str) -> str:
        text_l = (text or "").lower()
        communities = {
            "andaluc":    "Andalucía",
            "catalu":     "Cataluña",
            "madrid":     "Madrid",
            "valenc":     "Comunitat Valenciana",
            "eusk":       "País Vasco",
            "vasco":      "País Vasco",
            "galicia":    "Galicia",
            "castilla":   "Castilla y León",
            "extremadura":"Extremadura",
            "arag":       "Aragón",
        }
        for token, label in communities.items():
            if token in text_l:
                return label
        return "Nacional"


# ── RSS genérico ──────────────────────────────────────────────────────────────

class RSSScraper:
    """Scraper genérico para boletines con feed RSS o Atom."""

    def __init__(self, name: str, community: str, rss_url: str):
        self.name = name
        self.community = community
        self.rss_url = rss_url

    def scrape(self) -> list[Convocation]:
        log.info(f"{self.name}: consultando RSS {self.rss_url}")
        raw = fetch_url(self.rss_url)
        if not raw:
            log.warning(f"{self.name}: sin respuesta del RSS")
            return []
        return self._parse_feed(raw)

    def _parse_feed(self, xml_str: str) -> list[Convocation]:
        try:
            root = ET.fromstring(xml_str)
        except ET.ParseError as e:
            log.warning(f"{self.name}: XML inválido ({e}), intentando fallback HTML")
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
        if not text and tag == "link":
            text = (node.attrib.get("href") or "").strip()
        return text

    def _item_to_convocation(self, item, ns) -> Optional[Convocation]:
        title = self._get_text(item, "title", ns)
        link  = self._get_text(item, "link", ns)
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

        # Descargar el artículo completo para mejor relevancia y extracción
        article_text = fetch_url(link) if link else ""
        combined = f"{title}\n{description}\n{(article_text or '')[:2000]}"

        relevance = relevancy_score(combined)
        if relevance < 0.3:
            return None

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
            amount=extract_amount(combined),
            deadline=extract_deadline(combined),
            relevance=relevance,
        )

    def _parse_html_listing(self, html: str) -> list[Convocation]:
        """Fallback para portales sin RSS válido."""
        anchors = re.findall(
            r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
            html, re.I | re.S,
        )
        results = []
        for href, raw_label in anchors:
            label = unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", raw_label))).strip()
            if len(label) < 40:
                continue
            full_url = urljoin(self.rss_url, href)
            relevance = relevancy_score(label)
            if relevance < 0.3:
                continue
            results.append(Convocation(
                id=generate_id(self.name, full_url or label),
                title=label[:240],
                body=self.name,
                bulletin=self.name,
                community=self.community,
                date=datetime.now().strftime("%Y-%m-%d"),
                url=full_url,
                description=label[:400],
                relevance=relevance,
            ))
            if len(results) >= 100:
                break
        log.info(f"{self.name}: {len(results)} convocatorias (fallback HTML)")
        return results

    def _normalize_date(self, pub_date: str) -> str:
        if not pub_date:
            return datetime.now().strftime("%Y-%m-%d")
        for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d"):
            try:
                return datetime.strptime(pub_date[:30], fmt).strftime("%Y-%m-%d")
            except ValueError:
                continue
        return datetime.now().strftime("%Y-%m-%d")


# ── Scrapers autonómicos ──────────────────────────────────────────────────────
# FIX: URLs corregidas a los feeds RSS reales de cada boletín

class BOJAScraper(RSSScraper):
    def __init__(self):
        super().__init__(
            name="BOJA",
            community="Andalucía",
            # FIX: URL corregida al feed RSS real
            rss_url="https://www.juntadeandalucia.es/boja/rss/rss.xml",
        )


class DOGCScraper(RSSScraper):
    def __init__(self):
        super().__init__(
            name="DOGC",
            community="Cataluña",
            # FIX: URL corregida al feed RSS real
            rss_url="https://portaldogc.gencat.cat/utilsEADOP/PDF/RSS/RSS_DOGC_RSSCA.xml",
        )


class BOCMScraper(RSSScraper):
    def __init__(self):
        super().__init__(
            name="BOCM",
            community="Madrid",
            rss_url="https://www.bocm.es/rss/bocm_rss.xml",
        )


class DOGVScraper(RSSScraper):
    def __init__(self):
        super().__init__(
            name="DOGV",
            community="Comunitat Valenciana",
            # FIX: URL corregida al feed RSS real
            rss_url="https://www.dogv.gva.es/portal/rss/es/rss.xml",
        )


class BOPVScraper(RSSScraper):
    def __init__(self):
        super().__init__(
            name="BOPV",
            community="País Vasco",
            # FIX: URL corregida al feed RSS real
            rss_url="https://www.euskadi.eus/bopv2/datos/rss/bopv_es.xml",
        )


# ── BDNS ──────────────────────────────────────────────────────────────────────

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
            ref = str(item.get("numConvocatoria", ""))
            url = f"https://www.infosubvenciones.es/bdnstrans/GE/es/convocatoria/{ref}"
            amount = item.get("importeTotalConcedido")
            results.append(Convocation(
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
            ))
        log.info(f"BDNS: {len(results)} convocatorias")
        return results
