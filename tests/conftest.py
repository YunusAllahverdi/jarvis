"""Testlerin geliştiricinin makinesinden yalıtılması.

`Settings` üretimde `.env` dosyasını ve `JARVIS_*` ortam değişkenlerini
okur — olması gereken de budur. Ama testlerde aynı davranış, paketin
DOĞRULUĞUNU geliştiricinin yerel yapılandırmasına bağlar.

Bunu yaşayarak gördük: çalışma kökü ve karar politikası `.env`'e
yazıldığında, "workspace ayarlanmamışken dosya aracı kaydedilmez" ve
"varsayılan politika deterministiktir" testleri kırmızıya döndü. Kodda
hiçbir şey bozulmamıştı; testler yalnızca varsayılanları sınıyordu ve
varsayılanlar artık geçerli değildi.

Bunun asıl tehlikesi tersidir: aynı mekanizma, gerçekten bozuk bir
varsayılanı da `.env`'deki doğru değerle GİZLEYEBİLİRDİ. Yeşil bir suite,
o durumda hiçbir şey kanıtlamazdı.

Bu yüzden testler `.env`'i hiç okumaz ve süreçteki `JARVIS_*`
değişkenlerini görmez. Belirli bir ayarı sınamak isteyen test onu
`Settings(...)` çağrısında açıkça verir — okuyan da neyin sınandığını
o satırda görür.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

from app.config.settings import Settings


@pytest.fixture(autouse=True, scope="session")
def _isolate_settings_from_the_developer_environment() -> Iterator[None]:
    """`.env` ve `JARVIS_*` değişkenlerini test oturumu boyunca devre dışı bırakır."""

    original_env_file = Settings.model_config.get("env_file")
    removed = {
        key: value for key, value in os.environ.items() if key.startswith("JARVIS_")
    }

    Settings.model_config["env_file"] = None
    for key in removed:
        del os.environ[key]

    try:
        yield
    finally:
        # Geri alma, aynı süreçte başka bir şey çalıştırılırsa diye.
        Settings.model_config["env_file"] = original_env_file
        os.environ.update(removed)
