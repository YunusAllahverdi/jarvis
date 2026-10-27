# Jarvis — üretim görüntüsü (çok aşamalı).
#
# İki aşama vardır: `frontend`, React kabuğunu derler; `runtime`, Python
# bağımlılıklarını kurar ve derlenmiş kabuğu içine kopyalar. Tek görüntü tek
# adres sunar: tarayıcı yalnızca bu sunucuya bağlanır, CORS diye bir sorun
# oluşmaz.
#
# Kabuk derlenmezse backend yine de çalışır (yalnızca API sunar), ama bu
# görüntüde derleme zorunludur: üretim görüntüsünün arayüzsüz çıkması
# sessiz bir eksiklik olurdu.

# =====================================================================
# Aşama 1 — React kabuğunu derle (Create React App + craco, çıktı: build/)
# =====================================================================
FROM node:20-slim AS frontend

WORKDIR /frontend

# Bağımlılık katmanı ayrı tutulur: yalnızca kaynak değiştiğinde `yarn
# install` yeniden çalışmaz.
COPY frontend/package.json frontend/yarn.lock ./
RUN yarn install --frozen-lockfile --network-timeout 600000

COPY frontend/ ./
RUN yarn build

# =====================================================================
# Aşama 2 — Python çalışma zamanı
# =====================================================================
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# `curl` sağlık denetimi (HEALTHCHECK) için gereklidir; slim imajda yoktur.
RUN apt-get update \
    && apt-get install --no-install-recommends -y curl \
    && rm -rf /var/lib/apt/lists/*

# Önce yalnızca bağımlılık bildirimi kopyalanır: kaynak kodu değişse bile
# bağımlılık katmanı yeniden kullanılır.
COPY pyproject.toml README.md ./
COPY app ./app
RUN pip install .

# Derlenmiş kabuk, backend'in beklediği yola (`JARVIS_FRONTEND_DIR`
# varsayılanı) yerleştirilir.
COPY --from=frontend /frontend/build ./frontend/build

# Kalıcı veri (bellek/denetim SQLite dosyaları) buraya yazılır; compose'da
# bir volume ile bağlanır, böylece yeniden başlatma veriyi silmez. Dizin
# root iken oluşturulup sahipliği jarvis'e verilir — root olmayan kullanıcı
# sonradan `/` altında dizin açamaz.
ENV JARVIS_MEMORY_DB_PATH=/data/jarvis.db \
    JARVIS_AUDIT_DB_PATH=/data/jarvis-audit.db \
    JARVIS_HOST=0.0.0.0 \
    JARVIS_PORT=8000

# Root olmayan kullanıcı: konteyner ele geçirilse bile ayrıcalıklı çalışmaz.
RUN useradd --create-home --uid 10001 jarvis \
    && mkdir -p /data \
    && chown -R jarvis:jarvis /app /data
USER jarvis

EXPOSE 8000

# Sağlık denetimi: uygulama gerçekten yanıt veriyor mu? `/api/v1/health`
# kimlik doğrulamadan muaftır, bu yüzden denetim token gerektirmez.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/api/v1/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
