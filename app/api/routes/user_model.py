"""Öğrenilmiş kullanıcı modeli API'si (Learning / User Model).

Frontend sözleşmesi — bu uçlar bir "Jarvis beni ne kadar tanıyor?" panelini
tek başına besleyecek şekilde tasarlanmıştır:

    GET  /api/user/profile   → profilin tamamı (trait'ler + tür sayımları + istatistik)
    GET  /api/user/traits    → trait listesi (türe/güvene göre filtrelenebilir, sayfalanabilir)
    GET  /api/user/stats     → yalnızca etkileşim istatistikleri (hafif uç)
    POST /api/user/learn     → öğrenme geçişini çalıştırır ve neyin değiştiğini döndürür

Tasarım kuralları:
- GET uçları SALT OKUNURDUR; veritabanını asla değiştirmezler. Frontend
  bunları istediği sıklıkta çağırabilir.
- Tek yazma ucu `POST /api/user/learn`'dür ve açıkça tetiklenir. Öğrenme
  sohbet akışının içinde çalışmaz, bu yüzden bir sohbet cevabını hiçbir
  koşulda geciktiremez.
- Kullanıcı modeli bağlı değilse (ör. testlerin enjekte ettiği sahte bir
  sağlayıcıyla çalışan uygulama) uçlar 503 ve makine tarafından okunabilir
  bir `code` döndürür — mevcut chat ucundaki hata biçimiyle aynıdır.
- Yanıt modelleri doğrudan servis katmanının pydantic modelleridir; ayrı bir
  dönüşüm katmanı yoktur.
"""

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel

from app.learning.analyzer import InteractionStats
from app.learning.trait import TraitType, UserTrait
from app.services.learning_service import LearningPassResult, LearningService
from app.services.user_model_service import UserModelService, UserProfile

router = APIRouter(tags=["user-model"], prefix="/user")

_UNAVAILABLE_DETAIL = {
    "code": "user_model_unavailable",
    "message": (
        "Kullanıcı modeli bu uygulama örneğinde bağlı değil. "
        "Öğrenme yığını yalnızca gerçek (enjekte edilmemiş) sağlayıcı ile "
        "uygulama başlatıldığında kurulur."
    ),
}


class TraitListResponse(BaseModel):
    """`GET /api/user/traits` yanıtı."""

    traits: list[UserTrait]
    count: int
    """Döndürülen trait sayısı (toplam değil — sayfalama `offset` ile yapılır)."""


def _require_user_model(request: Request) -> UserModelService:
    """Bağlı UserModelService'i döndürür; yoksa 503 fırlatır."""
    service = getattr(request.app.state, "user_model_service", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_UNAVAILABLE_DETAIL,
        )
    return service


def _require_learning(request: Request) -> LearningService:
    """Bağlı LearningService'i döndürür; yoksa 503 fırlatır."""
    service = getattr(request.app.state, "learning_service", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_UNAVAILABLE_DETAIL,
        )
    return service


@router.get("/profile", response_model=UserProfile, status_code=status.HTTP_200_OK)
async def get_profile(
    request: Request,
    min_confidence: float = Query(default=0.0, ge=0.0, le=1.0),
    limit: int = Query(default=50, ge=1, le=200),
) -> UserProfile:
    """Öğrenilmiş kullanıcı profilinin güncel anlık görüntüsünü döndürür.

    `min_confidence` hem listelenen trait'leri hem tür sayımlarını filtreler,
    böylece gösterilen sayılar listeyle tutarlı kalır.
    """
    return _require_user_model(request).build_profile(
        min_confidence=min_confidence, limit=limit
    )


@router.get("/traits", response_model=TraitListResponse, status_code=status.HTTP_200_OK)
async def list_traits(
    request: Request,
    trait_type: TraitType | None = Query(default=None),
    min_confidence: float = Query(default=0.0, ge=0.0, le=1.0),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> TraitListResponse:
    """Etkin trait'leri güven sırasına göre döndürür (en güçlü önce)."""
    traits = _require_user_model(request).list_traits(
        trait_type=trait_type,
        min_confidence=min_confidence,
        limit=limit,
        offset=offset,
    )
    return TraitListResponse(traits=traits, count=len(traits))


@router.get("/stats", response_model=InteractionStats, status_code=status.HTTP_200_OK)
async def get_stats(request: Request) -> InteractionStats:
    """Etkileşim geçmişinin sayısal özetini döndürür (trait'ler olmadan)."""
    return _require_user_model(request).interaction_stats()


@router.post("/learn", response_model=LearningPassResult, status_code=status.HTTP_200_OK)
async def run_learning_pass(request: Request) -> LearningPassResult:
    """Bir öğrenme geçişi çalıştırır ve neyin değiştiğini döndürür.

    Geçiş idempotenttir: arka arkaya iki kez çağrılması kanıt sayılarını
    şişirmez, yalnızca aynı trait'leri tazeler.

    Beklenmedik bir hata olursa istisna fırlatılmaz; `failed=true` taşıyan
    bir sonuç döner (öğrenme, sohbet gibi kritik bir yol değildir).
    """
    return _require_learning(request).run_pass()
