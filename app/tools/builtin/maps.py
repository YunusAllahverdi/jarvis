"""Google Maps araçları — konum, yol tarifi ve yer arama.

İZİN SEVİYESİ NEDEN WRITE: Her Maps API çağrısı Google'a bir istek gönderir
ve dışarıya bir iz bırakır (IP adresi, arama sorgusu). Bu nedenle fetch_url
ile aynı gerekçeyle WRITE seviyesindedir: kullanıcı onayından geçer.

Bu modül üç araç sağlar:

- `maps_geocode`   : Metin adresini enlem/boylam koordinatlarına çevirir.
- `maps_directions`: İki nokta arasında yol tarifi alır (araba/yürüme/toplu taşıma).
- `maps_places`    : Yakınlardaki yerleri veya metin ile yer arar.

Araçlar yalnızca `JARVIS_MAPS_API_KEY` tanımlıysa kaydedilir; anahtarsız
bir Maps aracı anlamsız olurdu (her çağrı reddedilirdi).
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from pydantic import Field

from app.tools.base import PermissionLevel, Tool, ToolExecutionError, ToolInput

logger = logging.getLogger(__name__)

MAPS_GEOCODE_TOOL_NAME = "maps_geocode"
MAPS_DIRECTIONS_TOOL_NAME = "maps_directions"
MAPS_PLACES_TOOL_NAME = "maps_places"

_MAPS_BASE = "https://maps.googleapis.com/maps/api"
_DEFAULT_TIMEOUT = 15.0


# ── Geocode ──────────────────────────────────────────────────────────────────


class MapsGeocodeInput(ToolInput):
    address: str = Field(min_length=1, max_length=500, description="Koordinatlarına çevrilecek adres.")


class MapsGeocodeTool(Tool[MapsGeocodeInput]):
    """Bir adresi enlem/boylam koordinatlarına çevirir (geocoding)."""

    name = MAPS_GEOCODE_TOOL_NAME
    description = (
        "Bir metin adresini coğrafi koordinatlara (enlem/boylam) çevirir. "
        "Yol tarifi veya harita konumu gibi işlemlerin ön adımı olarak kullanılır."
    )
    permission = PermissionLevel.WRITE
    input_model = MapsGeocodeInput

    def __init__(self, *, api_key: str, timeout_seconds: float = _DEFAULT_TIMEOUT) -> None:
        self._api_key = api_key
        self._timeout = timeout_seconds

    async def execute(self, tool_input: MapsGeocodeInput) -> dict[str, Any]:
        params = {
            "address": tool_input.address,
            "key": self._api_key,
            "language": "tr",
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(f"{_MAPS_BASE}/geocode/json", params=params)
        except httpx.TimeoutException as exc:
            raise ToolExecutionError("Geocode isteği zaman aşımına uğradı.") from exc
        except httpx.RequestError as exc:
            raise ToolExecutionError("Google Maps API'sine bağlanılamadı.") from exc

        data = self._parse_json(response)
        status = data.get("status", "")
        if status == "ZERO_RESULTS":
            return {"address": tool_input.address, "found": False, "results": []}
        if status != "OK":
            raise ToolExecutionError(f"Geocode hatası: {status}")

        results = []
        for r in data.get("results", [])[:3]:
            loc = r.get("geometry", {}).get("location", {})
            results.append(
                {
                    "formatted_address": r.get("formatted_address", ""),
                    "lat": loc.get("lat"),
                    "lng": loc.get("lng"),
                    "place_id": r.get("place_id", ""),
                }
            )
        return {"address": tool_input.address, "found": True, "results": results}

    @staticmethod
    def _parse_json(response: httpx.Response) -> dict[str, Any]:
        try:
            return response.json()  # type: ignore[return-value]
        except Exception as exc:
            raise ToolExecutionError("Google Maps yanıtı çözümlenemedi.") from exc


# ── Directions ───────────────────────────────────────────────────────────────


class MapsDirectionsInput(ToolInput):
    origin: str = Field(min_length=1, max_length=500, description="Başlangıç noktası (adres veya enlem,boylam).")
    destination: str = Field(min_length=1, max_length=500, description="Bitiş noktası (adres veya enlem,boylam).")
    mode: str = Field(
        default="driving",
        description="Ulaşım modu: driving, walking, bicycling, transit.",
        pattern=r"^(driving|walking|bicycling|transit)$",
    )


class MapsDirectionsTool(Tool[MapsDirectionsInput]):
    """İki nokta arasında yol tarifi ve tahmini süre/mesafe bilgisi verir."""

    name = MAPS_DIRECTIONS_TOOL_NAME
    description = (
        "İki konum arasında yol tarifi, mesafe ve tahmini süre hesaplar. "
        "Ulaşım modu olarak araba (driving), yürüme (walking), bisiklet "
        "(bicycling) veya toplu taşıma (transit) seçilebilir."
    )
    permission = PermissionLevel.WRITE
    input_model = MapsDirectionsInput

    def __init__(self, *, api_key: str, timeout_seconds: float = _DEFAULT_TIMEOUT) -> None:
        self._api_key = api_key
        self._timeout = timeout_seconds

    async def execute(self, tool_input: MapsDirectionsInput) -> dict[str, Any]:
        params = {
            "origin": tool_input.origin,
            "destination": tool_input.destination,
            "mode": tool_input.mode,
            "key": self._api_key,
            "language": "tr",
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(f"{_MAPS_BASE}/directions/json", params=params)
        except httpx.TimeoutException as exc:
            raise ToolExecutionError("Yol tarifi isteği zaman aşımına uğradı.") from exc
        except httpx.RequestError as exc:
            raise ToolExecutionError("Google Maps API'sine bağlanılamadı.") from exc

        data: dict[str, Any]
        try:
            data = response.json()
        except Exception as exc:
            raise ToolExecutionError("Google Maps yanıtı çözümlenemedi.") from exc

        status = data.get("status", "")
        if status == "ZERO_RESULTS":
            return {
                "origin": tool_input.origin,
                "destination": tool_input.destination,
                "found": False,
                "routes": [],
            }
        if status != "OK":
            raise ToolExecutionError(f"Yol tarifi hatası: {status}")

        routes = []
        for route in data.get("routes", [])[:2]:
            legs = route.get("legs", [{}])
            leg = legs[0] if legs else {}
            steps_summary = []
            for step in leg.get("steps", [])[:8]:
                instruction = step.get("html_instructions", "")
                # HTML etiketlerini temizle
                import re
                clean = re.sub(r"<[^>]+>", " ", instruction).strip()
                distance = step.get("distance", {}).get("text", "")
                if clean:
                    steps_summary.append(f"{clean} ({distance})" if distance else clean)

            routes.append(
                {
                    "summary": route.get("summary", ""),
                    "distance": leg.get("distance", {}).get("text", ""),
                    "duration": leg.get("duration", {}).get("text", ""),
                    "start_address": leg.get("start_address", ""),
                    "end_address": leg.get("end_address", ""),
                    "steps": steps_summary,
                }
            )

        return {
            "origin": tool_input.origin,
            "destination": tool_input.destination,
            "mode": tool_input.mode,
            "found": True,
            "routes": routes,
        }


# ── Places ───────────────────────────────────────────────────────────────────


class MapsPlacesInput(ToolInput):
    query: str = Field(min_length=1, max_length=300, description="Aranacak yer adı veya türü (ör. 'istanbul kahve', 'eczane').")
    location: str | None = Field(
        default=None,
        max_length=100,
        description="Arama merkezi: 'enlem,boylam' biçiminde (ör. '41.0082,28.9784'). "
                    "Verilmezse global arama yapılır.",
    )
    radius_meters: int = Field(
        default=5000,
        ge=100,
        le=50000,
        description="Konum verildiğinde arama yarıçapı (metre). Varsayılan 5000.",
    )


class MapsPlacesTool(Tool[MapsPlacesInput]):
    """Metin sorgusuna göre yer arar; yakınlık filtresi eklenebilir."""

    name = MAPS_PLACES_TOOL_NAME
    description = (
        "Restoran, eczane, market gibi yer türlerini veya özel yer adlarını arar. "
        "İsteğe bağlı konum ve yarıçap ile yakın çevredeki yerler listelenebilir."
    )
    permission = PermissionLevel.WRITE
    input_model = MapsPlacesInput

    def __init__(self, *, api_key: str, timeout_seconds: float = _DEFAULT_TIMEOUT) -> None:
        self._api_key = api_key
        self._timeout = timeout_seconds

    async def execute(self, tool_input: MapsPlacesInput) -> dict[str, Any]:
        params: dict[str, Any] = {
            "query": tool_input.query,
            "key": self._api_key,
            "language": "tr",
        }
        if tool_input.location:
            params["location"] = tool_input.location
            params["radius"] = tool_input.radius_meters

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(
                    f"{_MAPS_BASE}/place/textsearch/json", params=params
                )
        except httpx.TimeoutException as exc:
            raise ToolExecutionError("Yer arama isteği zaman aşımına uğradı.") from exc
        except httpx.RequestError as exc:
            raise ToolExecutionError("Google Maps API'sine bağlanılamadı.") from exc

        data: dict[str, Any]
        try:
            data = response.json()
        except Exception as exc:
            raise ToolExecutionError("Google Maps yanıtı çözümlenemedi.") from exc

        status = data.get("status", "")
        if status == "ZERO_RESULTS":
            return {"query": tool_input.query, "found": False, "places": []}
        if status not in ("OK", "INVALID_REQUEST"):
            raise ToolExecutionError(f"Yer arama hatası: {status}")

        places = []
        for place in data.get("results", [])[:5]:
            loc = place.get("geometry", {}).get("location", {})
            places.append(
                {
                    "name": place.get("name", ""),
                    "address": place.get("formatted_address", ""),
                    "lat": loc.get("lat"),
                    "lng": loc.get("lng"),
                    "rating": place.get("rating"),
                    "open_now": place.get("opening_hours", {}).get("open_now"),
                    "types": place.get("types", [])[:3],
                }
            )

        return {"query": tool_input.query, "found": True, "places": places}
