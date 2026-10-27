# Yol haritası

Bu dosya, Jarvis'in planlanan yetenek parçalarını ve bunların durumunu
izler. Sıra bağlayıcı değildir; her parça bağımsız olarak çalışır hâlde
bırakılır ve **varsayılan kapalı** doğar.

| # | Parça | Durum | Notlar |
|---|---|---|---|
| 1 | Temel sağlamlaştırma (test altyapısı, CI) | ✅ Tamamlandı | 1508 test, CI yeşil |
| 2 | **Yetenek kaydı** (çok kaynaklı araç sözleşmesi, izin override) | ✅ Tamamlandı | `ToolProvider` + `CapabilityRegistry` + `ToolExecutor` sınırı |
| 3 | MCP sunucuları | ⏳ Sırada | `ToolProvider` sözleşmesinden geçecek |
| 4 | Home Assistant | ⏳ Planlı | Aynı sözleşme |
| 5 | Tarayıcı kontrolü | ⏳ Planlı | `untrusted_output=True` |
| 6 | Bilgisayar kontrolü | ⏳ Planlı | `risk_tags` ile sınıflandırılacak |

## Parça 2 — Yetenek kaydı (tamamlandı)

Çok kaynaklı araçlar için tek tip bir kayıt kuruldu. Sonraki parçaların hepsi
bu sözleşmeden geçer; iki paralel sistem bırakılmadı.

**Ne eklendi:**

- `app/tools/providers.py` — `ToolProvider` Protocol, `ProviderHealth`,
  `FunctionToolProvider` sarmalayıcı.
- `app/tools/capabilities.py` — `CapabilityRegistry`; sağlayıcıları toplar,
  paylaşılan `ToolRegistry`'yi `rebuild()` ile yerinde kurar.
- `app/tools/builtin_providers.py` — mevcut `register_*` fonksiyonlarını
  davranış değiştirmeden `builtin` sağlayıcıya sarar.
- `app/tools/base.py` — geriye uyumlu opsiyonel meta veriler (`source`,
  `category`, `risk_tags`, `untrusted_output`, `max_output_chars`,
  `timeout_seconds`).
- `app/security/tool_overrides.py` — SQLite'ta kalıcı override deposu.
- `app/security/permissions.py` — `ToolPermissionPolicy` / `plan_override`:
  izin kararının tek verildiği yer.
- `app/tools/executor.py` — araç başına timeout, çıktı kırpma, güvenilmez
  çıktı zarfı, kontrol karakteri temizliği.
- `app/api/routes/capabilities.py` — yönetim ve salt-okunur uçlar.
- `frontend/src/panels/CapabilitiesPanel.jsx` — sağlayıcı/araç listesi, izin
  rozetleri, aç/kapa ve yükseltme; düşürme için onay diyaloğu.

**Değişmeyen ilkeler:**

- Tek yürütme sınırı `ToolExecutor`'dır; ikinci bir yol açılmadı.
- İzin seviyesini model ya da dış sunucu belirleyemez.
- Yeni yetenekler varsayılan kapalı doğar; kapalıyken ağır bağımlılık import
  edilmez.
