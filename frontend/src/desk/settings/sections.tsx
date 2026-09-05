import { useCallback, useEffect, useState } from 'react';
import {
  apiClient,
  getApiToken,
  setApiToken,
  type ExperienceView,
  type LLMConfig,
  type LLMProviderKind,
  type MemoryRecordView,
  type SystemStatus,
} from '../../api/client';
import type { DeskPrefs } from '../useDeskPrefs';
import {
  Buttons, Group, NotWired, PanelHead, Row, Select, Slider, Stat, Status, Text, Toggle,
} from './rows';

/**
 * Kontrol merkezinin bölümleri.
 *
 * Her bölüm KENDİ verisini çeker. Ortak bir "tüm ayarları yükle"
 * çağrısı olsaydı, tek bir bölüme bakmak için sistem durumu, bellek
 * kayıtları ve deneyimlerin hepsi istenirdi — açılış her seferinde
 * yavaşlardı ve bir ucun 503'ü tüm paneli boş bırakırdı.
 */

export interface SectionProps {
  prefs: DeskPrefs;
  setPref: <K extends keyof DeskPrefs>(key: K, value: DeskPrefs[K]) => void;
  toast: (message: string) => void;
  /** Sağlayıcı değişince kabuk "model yok" uyarısını tazelesin diye. */
  onProviderChanged: () => void;
}

/* ── Genel bakış ───────────────────────────────────────────── */

export const OverviewSection = ({ toast }: SectionProps) => {
  const [config, setConfig] = useState<LLMConfig | null>(null);
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [counts, setCounts] = useState<{ notes: number; memories: number } | null>(null);

  useEffect(() => {
    // Her biri ayrı yakalanır: bellek ucu kapalıysa sistem durumu yine
    // görünmeli. Tek bir `Promise.all` hepsini birden düşürürdü.
    void apiClient.getLlmConfig().then(setConfig).catch(() => setConfig(null));
    void apiClient.getSystemStatus().then(setStatus).catch(() => setStatus(null));
    void Promise.all([
      apiClient.getNotes().then((r) => r.count).catch(() => 0),
      apiClient.getMemoryRecords('', 1).then((r) => r.count).catch(() => 0),
    ]).then(([notes, memories]) => setCounts({ notes, memories }));
  }, []);

  const modelReady = Boolean(config?.model?.trim());

  return (
    <>
      <PanelHead title="Ayarlar" sub="J.A.R.V.I.S ortamınızın denetimi." />

      <Group title="SAĞLAYICI">
        <Row label="Şu anki model" desc={config ? config.base_url : 'Okunamadı'}>
          <Status
            text={modelReady ? (config?.model as string) : 'model seçilmedi'}
            tone={modelReady ? 'on' : 'warn'}
          />
        </Row>
        <Row label="Tür" desc="Sağlayıcı ayarlarından değiştirilir.">
          <Stat value={config ? KIND_LABEL[config.kind] : '—'} />
        </Row>
        <Row label="API anahtarı" desc="Anahtar sunucuda kalır ve geri okunmaz.">
          <Status
            text={config?.has_api_key ? 'tanımlı' : 'yok'}
            tone={config?.has_api_key ? 'on' : config?.kind === 'ollama' ? 'off' : 'warn'}
          />
        </Row>
      </Group>

      <Group title="MAKİNE">
        {status ? (
          <>
            <Row label="İşlemci" desc={status.is_local ? 'Bu makine' : 'Sunucunun makinesi'}>
              <Stat value={`%${status.cpu_percent.toFixed(0)}`} />
            </Row>
            <Row label="Bellek" desc={`${gb(status.memory_available_bytes)} GB boş`}>
              <Stat value={`%${status.memory_percent.toFixed(0)}`} />
            </Row>
            <Row label="Disk" desc={`${gb(status.disk_free_bytes)} GB boş`}>
              <Stat value={`%${status.disk_percent.toFixed(0)}`} />
            </Row>
          </>
        ) : (
          <Row label="Ölçüm yok" desc="Sistem durumu ucu bu örnekte bağlı değil." />
        )}
      </Group>

      <Group title="VERİ">
        <Row label="Not" desc="Kalıcı, sizin ve ajanın yazdığı notlar.">
          <Stat value={String(counts?.notes ?? 0)} />
        </Row>
        <Row label="Bellek kaydı" desc="Konuşmalardan çıkarılmış bilgiler.">
          <Stat value={String(counts?.memories ?? 0)} />
        </Row>
        <Row label="Bağlantı" desc="Backend'in ayakta olup olmadığını sınar.">
          <Buttons
            items={[{
              label: 'Sınayın',
              onClick: () => {
                void apiClient
                  .getHealth()
                  .then((health) => toast(`Sunucu yanıt verdi: ${health.status}`))
                  .catch((error: unknown) =>
                    toast(error instanceof Error ? error.message : 'Ulaşılamadı.'),
                  );
              },
            }]}
          />
        </Row>
      </Group>
    </>
  );
};

/* ── Sağlayıcı ─────────────────────────────────────────────── */

const KIND_LABEL: Record<LLMProviderKind, string> = {
  ollama: 'Ollama (yerel)',
  anthropic: 'Anthropic',
  openai_compatible: 'OpenAI uyumlu',
};

const KIND_BASE_URL: Record<LLMProviderKind, string> = {
  ollama: 'http://127.0.0.1:11434',
  anthropic: 'https://api.anthropic.com',
  openai_compatible: 'https://generativelanguage.googleapis.com/v1beta/openai',
};

const KIND_MODEL_HINT: Record<LLMProviderKind, string> = {
  ollama: 'ör. llama3.2',
  anthropic: 'ör. claude-haiku-4-5',
  openai_compatible: 'ör. gemini-2.0-flash',
};

const NEEDS_KEY: LLMProviderKind[] = ['anthropic', 'openai_compatible'];

export const ProviderSection = ({ toast, onProviderChanged }: SectionProps) => {
  const [kind, setKind] = useState<LLMProviderKind>('ollama');
  const [baseUrl, setBaseUrl] = useState('');
  const [model, setModel] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [hasKey, setHasKey] = useState(false);
  const [busy, setBusy] = useState(false);

  const apply = useCallback((config: LLMConfig) => {
    setKind(config.kind);
    setBaseUrl(config.base_url);
    setModel(config.model ?? '');
    setHasKey(config.has_api_key);
    // Anahtar alanı her kayıttan sonra BOŞALIR: panel anahtarı geri
    // okuyamaz, dolayısıyla dolu bırakmak "bu yazılı" yanılgısı yaratırdı.
    setApiKey('');
  }, []);

  useEffect(() => {
    void apiClient.getLlmConfig().then(apply).catch(() => toast('Ayarlar okunamadı.'));
  }, [apply, toast]);

  const chooseKind = (next: LLMProviderKind) => {
    setKind(next);
    // Kullanıcının kendi yazdığı adres EZİLMEZ; yalnızca boşsa ya da
    // önerilerden biriyse değiştirilir.
    if (!baseUrl.trim() || Object.values(KIND_BASE_URL).includes(baseUrl.trim())) {
      setBaseUrl(KIND_BASE_URL[next]);
    }
  };

  const save = async () => {
    setBusy(true);
    try {
      const saved = await apiClient.updateLlmConfig({
        kind,
        base_url: baseUrl.trim(),
        model: model.trim() || null,
        ...(apiKey.trim() ? { api_key: apiKey.trim() } : {}),
      });
      apply(saved);
      onProviderChanged();
      toast('Kaydedildi ve devreye alındı.');
    } catch (cause: unknown) {
      toast(cause instanceof Error ? cause.message : 'Kaydedilemedi.');
    } finally {
      setBusy(false);
    }
  };

  const clearKey = async () => {
    setBusy(true);
    try {
      const saved = await apiClient.updateLlmConfig({
        kind, base_url: baseUrl.trim(), model: model.trim() || null, clear_api_key: true,
      });
      apply(saved);
      toast('Anahtar silindi.');
    } catch (cause: unknown) {
      toast(cause instanceof Error ? cause.message : 'Silinemedi.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <PanelHead
        title="Sağlayıcı"
        sub="Jarvis'in hangi modeli kullanacağı. Değişiklik yeniden başlatma gerektirmez."
      />

      <Group title="BAĞLANTI">
        <Row label="Sağlayıcı" desc="Ollama yerelde çalışır ve anahtar istemez.">
          <Select
            value={kind}
            onChange={(next) => chooseKind(next as LLMProviderKind)}
            options={(Object.keys(KIND_LABEL) as LLMProviderKind[]).map((value) => ({
              value, label: KIND_LABEL[value],
            }))}
          />
        </Row>
        <Row label="Adres" desc="Sağlayıcının kök adresi.">
          <Text value={baseUrl} onChange={setBaseUrl} placeholder="https://..." width={280} />
        </Row>
        <Row label="Model" desc={KIND_MODEL_HINT[kind]}>
          <Text value={model} onChange={setModel} placeholder={KIND_MODEL_HINT[kind]} width={280} />
        </Row>
        {NEEDS_KEY.includes(kind) ? (
          <Row
            label="API anahtarı"
            desc={
              hasKey
                ? 'Tanımlı. Boş bırakırsanız mevcut anahtar korunur.'
                : 'Anahtar sunucuda kalır ve buraya geri gelmez.'
            }
          >
            <Text
              type="password"
              value={apiKey}
              onChange={setApiKey}
              placeholder={hasKey ? 'Değiştirmek için yeni anahtar' : 'Anahtarı yapıştırın'}
              width={280}
            />
          </Row>
        ) : null}
        <Row label="Uygula" desc="Kaydedilen ayar sunucuda hemen devreye girer.">
          <Buttons
            items={[
              { label: busy ? 'Kaydediliyor...' : 'Kaydet', onClick: () => void save() },
              ...(hasKey ? [{ label: 'Anahtarı sil', onClick: () => void clearKey(), danger: true }] : []),
            ]}
          />
        </Row>
      </Group>
    </>
  );
};

/* ── Görünüm ───────────────────────────────────────────────── */

export const AppearanceSection = ({ prefs, setPref }: SectionProps) => (
  <>
    <PanelHead
      title="Görünüm"
      sub="Bu ayarlar yalnızca bu cihazda geçerlidir; sunucuya yazılmaz."
    />
    <Group title="MASA">
      <Row label="Masa ızgarası" desc="Masa modundaki zemin deseni.">
        <Toggle on={prefs.grid} onChange={(next) => setPref('grid', next)} />
      </Row>
    </Group>
    <Group title="KÜRE">
      <Row label="Animasyon" desc="Kapalıyken küre donar; pil ömrü için.">
        <Toggle on={prefs.orbAnimated} onChange={(next) => setPref('orbAnimated', next)} />
      </Row>
      <Row label="Boyut" desc="Ana ekrandaki çap.">
        <Slider
          value={prefs.orbSize}
          min={120}
          max={360}
          step={10}
          readout={`${prefs.orbSize} px`}
          onChange={(next) => setPref('orbSize', next)}
        />
      </Row>
    </Group>
  </>
);

/* ── Ses ───────────────────────────────────────────────────── */

export const VoiceSection = ({ prefs, setPref }: SectionProps) => (
  <>
    <PanelHead
      title="Ses"
      sub="Ses tarayıcının kendi motorunu kullanır; hiçbir ses kaydı sunucuya gitmez."
    />
    <Group title="YANIT">
      <Row label="Sesli yanıt" desc="Cevaplar geldikçe yüksek sesle okunur.">
        <Toggle on={prefs.voice} onChange={(next) => setPref('voice', next)} />
      </Row>
    </Group>
    <Group title="GİRİŞ">
      <Row
        label="Bas-konuş"
        desc="Giriş çubuğundaki mikrofon düğmesi basılı tutulduğu sürece dinler."
      >
        <Status text="tarayıcıda" tone="on" />
      </Row>
    </Group>
  </>
);

/* ── Bellek ────────────────────────────────────────────────── */

export const MemorySection = () => {
  const [records, setRecords] = useState<MemoryRecordView[] | null>(null);
  const [query, setQuery] = useState('');

  useEffect(() => {
    const id = window.setTimeout(() => {
      void apiClient
        .getMemoryRecords(query, 20)
        .then((result) => setRecords(result.records))
        .catch(() => setRecords([]));
    }, 250);
    return () => window.clearTimeout(id);
  }, [query]);

  return (
    <>
      <PanelHead
        title="Bellek"
        sub="Konuşmalardan çıkarılmış bilgiler. Silme mantıksaldır: kayıt kalır, geçerliliği biter."
      />
      <Group title="ARAMA">
        <Row label="Kayıtlarda ara">
          <Text value={query} onChange={setQuery} placeholder="anahtar kelime" width={280} />
        </Row>
      </Group>
      <Group title={`KAYITLAR${records ? ` · ${records.length}` : ''}`}>
        {records === null ? (
          <Row label="Yükleniyor..." />
        ) : records.length === 0 ? (
          <Row label="Kayıt yok" desc="Henüz çıkarılmış bir bilgi bulunmuyor." />
        ) : (
          records.map((record) => (
            <Row key={record.id} label={record.content} desc={`${record.memory_type} · önem ${record.importance.toFixed(2)}`} />
          ))
        )}
      </Group>
    </>
  );
};

/* ── Konuşma geçmişi ───────────────────────────────────────── */

export const ConversationSection = () => {
  const [items, setItems] = useState<ExperienceView[] | null>(null);

  useEffect(() => {
    void apiClient
      .getExperiences(20)
      .then((result) => setItems(result.experiences))
      .catch(() => setItems([]));
  }, []);

  return (
    <>
      <PanelHead title="Konuşma" sub="Son etkileşimler ve kullanılan araçlar." />
      <Group title="GEÇMİŞ">
        {items === null ? (
          <Row label="Yükleniyor..." />
        ) : items.length === 0 ? (
          <Row label="Henüz konuşma yok" />
        ) : (
          items.map((item) => (
            <Row
              key={item.id}
              label={item.user_message}
              desc={`${item.outcome}${item.tool_calls.length ? ` · ${item.tool_calls.join(', ')}` : ''}`}
            />
          ))
        )}
      </Group>
    </>
  );
};

/* ── Araçlar ve izinler ────────────────────────────────────── */

interface ToolRow {
  name: string;
  description: string;
  permission: string;
}

export const ToolsSection = () => {
  const [tools, setTools] = useState<ToolRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void fetch('/api/agent/tools', {
      headers: getApiToken() ? { 'X-Jarvis-Token': getApiToken() } : {},
    })
      .then(async (response) => {
        if (!response.ok) throw new Error('Ajan bu örnekte bağlı değil.');
        return response.json() as Promise<{ tools: ToolRow[] }>;
      })
      .then((data) => setTools(data.tools))
      .catch((cause: unknown) =>
        setError(cause instanceof Error ? cause.message : 'Araçlar okunamadı.'),
      );
  }, []);

  return (
    <>
      <PanelHead
        title="İzinler"
        sub="Ajanın gerçekten elinde olan araçlar. Bu liste ayar değil, DURUM: kapalı bir yetenek burada hiç görünmez."
      />
      <Group title="KAYITLI ARAÇLAR">
        {error ? (
          <Row label={error} desc="Ajan kapalıyken hiçbir araç kayıtlı değildir." />
        ) : tools === null ? (
          <Row label="Yükleniyor..." />
        ) : tools.length === 0 ? (
          <Row label="Araç yok" desc="Her yetenek varsayılan olarak kapalıdır." />
        ) : (
          tools.map((tool) => (
            <Row key={tool.name} label={tool.name} desc={tool.description}>
              <Status
                text={tool.permission}
                tone={tool.permission === 'read' ? 'on' : 'warn'}
              />
            </Row>
          ))
        )}
      </Group>
    </>
  );
};

/* ── Güvenlik ──────────────────────────────────────────────── */

export const SecuritySection = ({ toast }: SectionProps) => {
  const [token, setToken] = useState('');
  const stored = getApiToken();

  return (
    <>
      <PanelHead
        title="Erişim"
        sub="Sunucu ağa açıldığında (tabletten kullanmak için) anahtar zorunlu olur."
      />
      <Group title="BU CİHAZIN ANAHTARI">
        <Row
          label="Durum"
          desc={
            stored
              ? 'Anahtar bu tarayıcıda saklı ve her isteğe ekleniyor.'
              : 'Anahtar yok. Yerelde çalışırken gerekmez.'
          }
        >
          <Status text={stored ? 'tanımlı' : 'yok'} tone={stored ? 'on' : 'off'} />
        </Row>
        <Row label="Yeni anahtar" desc="Sunucudaki JARVIS_API_TOKEN değeriyle aynı olmalı.">
          <Text type="password" value={token} onChange={setToken} placeholder="anahtarı yapıştırın" width={280} />
        </Row>
        <Row label="Uygula">
          <Buttons
            items={[
              {
                label: 'Kaydet',
                onClick: () => {
                  setApiToken(token.trim());
                  setToken('');
                  toast('Anahtar kaydedildi.');
                },
              },
              ...(stored
                ? [{
                    label: 'Anahtarı sil',
                    danger: true,
                    onClick: () => { setApiToken(''); toast('Anahtar silindi.'); },
                  }]
                : []),
            ]}
          />
        </Row>
      </Group>
    </>
  );
};

/* ── Hakkında ──────────────────────────────────────────────── */

export const AboutSection = () => {
  const [health, setHealth] = useState<string>('...');

  useEffect(() => {
    void apiClient
      .getHealth()
      .then((result) => setHealth(result.version ? `${result.status} · ${result.version}` : result.status))
      .catch(() => setHealth('ulaşılamıyor'));
  }, []);

  return (
    <>
      <PanelHead title="J.A.R.V.I.S" sub="Kişisel, yerel çalışan bir asistan." />
      <Group title="SUNUCU">
        <Row label="Durum">
          <Status text={health} tone={health === 'ulaşılamıyor' ? 'warn' : 'on'} />
        </Row>
        <Row label="Veri" desc="Notlar, bellek ve ayarlar bu makinedeki SQLite dosyasında durur." />
      </Group>
    </>
  );
};

/* ── Henüz bağlı olmayanlar ────────────────────────────────── */

export const IntegrationsSection = () => (
  <>
    <PanelHead
      title="Entegrasyonlar"
      sub="Dış servisler henüz bağlı değil."
    />
    <NotWired
      what="Gmail, Takvim, GitHub, Spotify ve Hava Durumu"
      needs="Her biri için OAuth akışı, bir araç ve onay kuralları gerekiyor. Ajanın gerçekten elinde olan araçları İzinler bölümünde görebilirsiniz."
    />
  </>
);

export const AutomationSection = () => (
  <>
    <PanelHead title="Otomasyon" sub="Zamanlanmış işler ve tetikleyiciler." />
    <NotWired
      what="Zamanlanmış eylemler, iş akışları ve tetikleyiciler"
      needs="Bunlar için sunucuda bir zamanlayıcı ve çalıştırma günlüğü gerekiyor. Şimdilik ajan yalnızca siz istediğinizde çalışır."
    />
  </>
);

const gb = (bytes: number) => (bytes / 1024 ** 3).toFixed(1);
