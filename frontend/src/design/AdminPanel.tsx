import { useCallback, useEffect, useState } from 'react';
import {
  apiClient,
  type LLMConfig,
  type LLMProviderKind,
} from '../api/client';

/**
 * Sağlayıcı ayarlarının değiştirildiği panel.
 *
 * Anahtar alanı bilerek boş açılır ve boş bırakılırsa sunucudaki mevcut
 * anahtar korunur — panel anahtarı geri okuyamaz, dolayısıyla onu burada
 * gösterme ya da her kaydetmede yeniden isteme ihtimali yoktur.
 */

const PANEL: React.CSSProperties = {
  borderRadius: 15,
  background: 'rgba(14,13,32,0.92)',
  border: '1px solid rgba(140,150,255,0.18)',
  backdropFilter: 'blur(20px)',
};

const LABEL: React.CSSProperties = {
  fontSize: 11,
  letterSpacing: '0.06em',
  textTransform: 'uppercase',
  color: '#8b96c8',
};

const FIELD: React.CSSProperties = {
  width: '100%',
  height: 38,
  padding: '0 12px',
  borderRadius: 10,
  background: 'rgba(140,150,255,0.06)',
  border: '1px solid rgba(140,150,255,0.16)',
  color: '#dfe2ff',
  fontSize: 13,
  fontFamily: 'inherit',
  outline: 'none',
};

/** Sağlayıcı seçildiğinde önerilen adres — kullanıcı yine değiştirebilir. */
const SUGGESTED_BASE_URL: Record<LLMProviderKind, string> = {
  ollama: 'http://127.0.0.1:11434',
  openai_compatible: 'https://generativelanguage.googleapis.com/v1beta/openai',
};

interface Props {
  onClose: () => void;
}

export const AdminPanel = ({ onClose }: Props) => {
  const [kind, setKind] = useState<LLMProviderKind>('ollama');
  const [baseUrl, setBaseUrl] = useState('');
  const [model, setModel] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [hasKey, setHasKey] = useState(false);

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<{ text: string; ok: boolean } | null>(null);

  const apply = useCallback((config: LLMConfig) => {
    setKind(config.kind);
    setBaseUrl(config.base_url);
    setModel(config.model ?? '');
    setHasKey(config.has_api_key);
    setApiKey('');
  }, []);

  useEffect(() => {
    let cancelled = false;
    apiClient
      .getLlmConfig()
      .then((config) => { if (!cancelled) apply(config); })
      .catch((error: unknown) => {
        if (cancelled) return;
        setMessage({
          text: error instanceof Error ? error.message : 'Ayarlar okunamadı.',
          ok: false,
        });
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [apply]);

  const save = useCallback(async () => {
    setSaving(true);
    setMessage(null);
    try {
      const config = await apiClient.updateLlmConfig({
        kind,
        base_url: baseUrl.trim(),
        model: model.trim() || null,
        // Boş bırakıldıysa alan hiç gönderilmez ve sunucudaki anahtar kalır.
        ...(apiKey.trim() ? { api_key: apiKey.trim() } : {}),
      });
      apply(config);
      setMessage({ text: 'Kaydedildi ve devreye alındı.', ok: true });
    } catch (error: unknown) {
      setMessage({
        text: error instanceof Error ? error.message : 'Kaydedilemedi.',
        ok: false,
      });
    } finally {
      setSaving(false);
    }
  }, [kind, baseUrl, model, apiKey, apply]);

  const clearKey = useCallback(async () => {
    setSaving(true);
    setMessage(null);
    try {
      const config = await apiClient.updateLlmConfig({
        kind,
        base_url: baseUrl.trim(),
        model: model.trim() || null,
        clear_api_key: true,
      });
      apply(config);
      setMessage({ text: 'Anahtar silindi.', ok: true });
    } catch (error: unknown) {
      setMessage({
        text: error instanceof Error ? error.message : 'Silinemedi.',
        ok: false,
      });
    } finally {
      setSaving(false);
    }
  }, [kind, baseUrl, model, apply]);

  const chooseKind = (next: LLMProviderKind) => {
    setKind(next);
    // Adres önerisi yalnızca kullanıcı henüz kendi adresini yazmadıysa
    // uygulanır; yazdığı bir adresi ezmek istemeyiz.
    if (!baseUrl.trim() || Object.values(SUGGESTED_BASE_URL).includes(baseUrl.trim())) {
      setBaseUrl(SUGGESTED_BASE_URL[next]);
    }
  };

  return (
    <div
      onClick={onClose}
      style={{
        position: 'absolute', inset: 0, zIndex: 20,
        background: 'rgba(4,3,12,0.55)',
        display: 'grid', placeItems: 'center',
      }}
    >
      <div
        onClick={(event) => event.stopPropagation()}
        role="dialog"
        aria-label="Sağlayıcı ayarları"
        style={{ ...PANEL, width: 460, padding: 22, display: 'flex', flexDirection: 'column', gap: 16 }}
      >
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div style={{ fontSize: 14, fontWeight: 500, color: '#dfe2ff' }}>Sağlayıcı Ayarları</div>
          <button
            onClick={onClose}
            aria-label="Kapat"
            style={{
              width: 28, height: 28, borderRadius: 8, cursor: 'pointer',
              background: 'transparent', border: '1px solid rgba(140,150,255,0.16)',
              color: '#aab4e8', fontSize: 14, lineHeight: 1,
            }}
          >
            ×
          </button>
        </div>

        {loading ? (
          <div style={{ fontSize: 13, color: '#8b96c8' }}>Yükleniyor...</div>
        ) : (
          <>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 7 }}>
              <span style={LABEL}>Sağlayıcı</span>
              <div style={{ display: 'flex', gap: 8 }}>
                {(['ollama', 'openai_compatible'] as LLMProviderKind[]).map((option) => (
                  <button
                    key={option}
                    onClick={() => chooseKind(option)}
                    style={{
                      flex: 1, height: 36, borderRadius: 10, cursor: 'pointer', fontSize: 12.5,
                      background: kind === option ? 'rgba(112,92,255,0.24)' : 'rgba(140,150,255,0.06)',
                      border: `1px solid ${kind === option ? 'rgba(150,130,255,0.45)' : 'rgba(140,150,255,0.16)'}`,
                      color: kind === option ? '#cfc4ff' : '#9aa4cc',
                      fontFamily: 'inherit',
                    }}
                  >
                    {option === 'ollama' ? 'Ollama (yerel)' : 'OpenAI uyumlu'}
                  </button>
                ))}
              </div>
            </div>

            <label style={{ display: 'flex', flexDirection: 'column', gap: 7 }}>
              <span style={LABEL}>Adres</span>
              <input
                value={baseUrl}
                onChange={(event) => setBaseUrl(event.target.value)}
                placeholder="https://..."
                style={FIELD}
              />
            </label>

            <label style={{ display: 'flex', flexDirection: 'column', gap: 7 }}>
              <span style={LABEL}>Model</span>
              <input
                value={model}
                onChange={(event) => setModel(event.target.value)}
                placeholder="ör. gemma3"
                style={FIELD}
              />
            </label>

            {kind === 'openai_compatible' && (
              <label style={{ display: 'flex', flexDirection: 'column', gap: 7 }}>
                <span style={LABEL}>
                  API anahtarı {hasKey && <span style={{ color: '#4ade9b' }}>· tanımlı</span>}
                </span>
                <input
                  type="password"
                  value={apiKey}
                  onChange={(event) => setApiKey(event.target.value)}
                  placeholder={hasKey ? 'Değiştirmek için yeni anahtarı yazın' : 'Anahtarı yapıştırın'}
                  autoComplete="off"
                  style={FIELD}
                />
                <span style={{ fontSize: 11, color: '#6f7aa5' }}>
                  Anahtar sunucuda kalır ve buraya geri gelmez. Boş bırakırsanız mevcut
                  anahtar korunur.
                </span>
              </label>
            )}

            {message && (
              <div
                role="status"
                style={{
                  fontSize: 12.5,
                  color: message.ok ? '#8fd9b6' : '#f1798f',
                  lineHeight: 1.5,
                }}
              >
                {message.text}
              </div>
            )}

            <div style={{ display: 'flex', gap: 8, marginTop: 2 }}>
              <button
                onClick={() => void save()}
                disabled={saving || !baseUrl.trim()}
                style={{
                  flex: 1, height: 40, borderRadius: 11,
                  cursor: saving || !baseUrl.trim() ? 'default' : 'pointer',
                  background: 'rgba(124,92,255,0.30)',
                  border: '1px solid rgba(170,150,255,0.55)',
                  color: '#dfe0ff', fontSize: 13, fontFamily: 'inherit',
                }}
              >
                {saving ? 'Kaydediliyor...' : 'Kaydet'}
              </button>
              {hasKey && (
                <button
                  onClick={() => void clearKey()}
                  disabled={saving}
                  style={{
                    height: 40, padding: '0 14px', borderRadius: 11, cursor: 'pointer',
                    background: 'transparent',
                    border: '1px solid rgba(241,121,143,0.35)',
                    color: '#f1798f', fontSize: 12.5, fontFamily: 'inherit',
                  }}
                >
                  Anahtarı sil
                </button>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
};
