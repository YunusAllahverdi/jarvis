"""Müzakere başına üretilen kimlik ↔ anonim etiket eşlemesi.

Neden ayrı bir modül?
    Model/üye kimliğinin prompt'lara sızmaması bir GÜVENLİK sınırıdır ve
    tek bir yerde uygulanmalıdır. Eşleme yalnızca orkestrasyon katmanında
    tutulur; prompt üreten kod (bkz. `app.council.prompts`) etiket dışında
    hiçbir kimlik bilgisi görmez.

Kurallar:
- Eşleme HER MÜZAKERE İÇİN YENİDEN üretilir. Global veya statik durum yoktur;
  `LabelMap` bir örnek nesnedir, modül düzeyinde hiçbir sözlük tutulmaz.
- Etiketler üye sırasına göre deterministik olarak atanır (A, B, C, ...).
  Bu, testleri okunabilir kılar; anonimliği sağlayan şey rastgelelik değil,
  gerçek kimliğin prompt'a HİÇ girmemesidir.

DÜRÜST SINIR:
    Anonimleştirme "bağlanamazlık" (unlinkability) DEĞİLDİR. Bir model kendi
    yazım stilini tanıyabilir. Yapabileceğimizin en iyisi, bir üyeye kendi
    adayını hiç göstermemek ve gerçek kimlikleri prompt dışında tutmaktır.
"""

from __future__ import annotations

from collections.abc import Sequence
from string import ascii_uppercase

from app.council.models import MAX_LABEL_COUNT


class LabelMap:
    """Tek bir müzakereye ait kimlik ↔ etiket eşlemesi."""

    def __init__(self, member_ids: Sequence[str]) -> None:
        """
        Args:
            member_ids: Üye kimlikleri, sabit sırada.

        Raises:
            ValueError: Kimlikler benzersiz değilse veya etiket sayısı
                sınırını aşıyorsa.
        """
        if len(set(member_ids)) != len(member_ids):
            raise ValueError("üye kimlikleri benzersiz olmalı")
        if len(member_ids) > MAX_LABEL_COUNT:
            raise ValueError(f"en fazla {MAX_LABEL_COUNT} üye etiketlenebilir")

        self._to_label = {
            member_id: ascii_uppercase[index] for index, member_id in enumerate(member_ids)
        }
        self._to_member = {label: member_id for member_id, label in self._to_label.items()}

    def label_for(self, member_id: str) -> str:
        """Üye kimliğinin anonim etiketini döndürür."""
        try:
            return self._to_label[member_id]
        except KeyError as exc:
            raise KeyError(f"bilinmeyen üye: {member_id}") from exc

    def member_for(self, label: str) -> str | None:
        """Etiketin ait olduğu üye kimliğini döndürür; bilinmiyorsa None."""
        return self._to_member.get(label)

    def knows_label(self, label: str) -> bool:
        """Etiket bu müzakerede tanımlı mı?"""
        return label in self._to_member

    @property
    def labels(self) -> list[str]:
        """Tüm etiketler, üye sırasında."""
        return list(self._to_member)

    def __len__(self) -> int:
        return len(self._to_label)
