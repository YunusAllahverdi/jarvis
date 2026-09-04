import { useCallback, useEffect, useState } from 'react';
import { apiClient, setApiToken, AuthRequiredError } from '../api/client';

/**
 * Anahtar giriş ekranı.
 *
 * Sunucu ağa açıldığında (bilgisayar açık, tabletten kullanılıyor) anahtar
 * zorunlu olur ve o anahtar tarayıcıda bir kez girilmelidir.
 *
 * NEDEN AÇILIŞTA DEĞİL DE HATADA: yerelde çalışan kullanıcı için anahtar
 * gerekmiyor ve ona her açılışta boş bir giriş ekranı göstermek, olmayan bir
 * engel uydurmak olurdu. Ekran yalnızca sunucu GERÇEKTEN anahtar istediğinde
 * belirir; yani gerekliliğini sunucu söyler, arayüz tahmin etmez.
 *
 * Anahtar denenmeden kaydedilmez: yanlış bir anahtarı kaydedip "tamam"
 * demek, kullanıcıyı çalışmayan bir kabukla baş başa bırakırdı.
 */

const PANEL: React.CSSProperties = {
  borderRadius: 15,
  background: 'rgba(14,13,32,0.94)',
  border: '1px solid rgba(140,150,255,0.18)',
  backdropFilter: 'blur(20px)',
};

interface Props {
  /** Anahtar doğrulandığında çağrılır. */
  onAuthorized: () => void;
  /** Sunucunun döndürdüğü açıklama; neden istendiğini söyler. */
  message?: string;
}

export const TokenGate = ({ onAuthorized, message }: Props) => {
  const [token, setToken] = useState('');
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = useCallback(async () => {
    const candidate = token.trim();
    if (!candidate || checking) return;

    setChecking(true);
    setError(null);
    // Denemeden önce geçici olarak kurulur; istek bu anahtarla gider.
    setApiToken(candidate);
    try {
      // Kimlik gerektiren, yan etkisiz bir uç: anahtarın gerçekten geçerli
      // olduğunu kanıtlar. Sağlık ucu muaf olduğu için işe yaramazdı.
      await apiClient.getSystemStatus();
      onAuthorized();
    } catch (err: unknown) {
      if (err instanceof AuthRequiredError) {
        setApiToken('');
        setError('Anahtar kabul edilmedi.');
      } else {
        // Sunucuya ulaşılamıyor olabilir; anahtar yanlış demek haksızlık
        // olurdu, bu yüzden silinmez.
        setError(err instanceof Error ? err.message : 'Doğrulanamadı.');
      }
    } finally {
      setChecking(false);
    }
  }, [token, checking, onAuthorized]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Enter') void submit();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [submit]);

  return (
    <div
      role="dialog"
      aria-label="Anahtar gerekiyor"
      style={{
        position: 'fixed', inset: 0, zIndex: 40,
        background: '#04030c', display: 'grid', placeItems: 'center', padding: 20,
        fontFamily: 'Sora, Helvetica, sans-serif',
      }}
    >
      <div style={{ ...PANEL, width: 'min(420px, 100%)', padding: 24, display: 'flex', flexDirection: 'column', gap: 14 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 11 }}>
          <div style={{ width: 11, height: 11, borderRadius: '50%', background: '#a78bfa', boxShadow: '0 0 14px 4px rgba(167,139,250,0.7)' }} />
          <div style={{ fontSize: 13, letterSpacing: '0.42em', fontWeight: 500, color: '#dfe2ff' }}>JARVIS</div>
        </div>

        <div style={{ fontSize: 13, color: '#aab4e8', lineHeight: 1.6 }}>
          {message ?? 'Bu sunucu bir anahtar istiyor.'}
        </div>

        <input
          type="password"
          value={token}
          onChange={(event) => setToken(event.target.value)}
          placeholder="Anahtarı yapıştırın"
          aria-label="Anahtar"
          autoComplete="off"
          autoFocus
          style={{
            width: '100%', height: 42, padding: '0 14px', borderRadius: 10,
            background: 'rgba(140,150,255,0.06)', border: '1px solid rgba(140,150,255,0.16)',
            color: '#dfe2ff', fontSize: 14, fontFamily: 'inherit', outline: 'none',
            boxSizing: 'border-box',
          }}
        />

        {error && (
          <div role="status" style={{ fontSize: 12.5, color: '#f1798f', lineHeight: 1.5 }}>
            {error}
          </div>
        )}

        <button
          onClick={() => void submit()}
          disabled={checking || !token.trim()}
          style={{
            height: 42, borderRadius: 11,
            cursor: checking || !token.trim() ? 'default' : 'pointer',
            background: token.trim() && !checking ? 'rgba(124,92,255,0.30)' : 'rgba(140,150,255,0.08)',
            border: '1px solid rgba(170,150,255,0.45)',
            color: '#dfe0ff', fontSize: 13.5, fontFamily: 'inherit',
          }}
        >
          {checking ? 'Doğrulanıyor...' : 'Bağlan'}
        </button>

        <div style={{ fontSize: 11, color: '#6f7aa5', lineHeight: 1.6 }}>
          Anahtar bu cihazda saklanır ve sunucuya her istekte gönderilir.
          Sunucudaki karşılığı <code style={{ color: '#8b96c8' }}>JARVIS_API_TOKEN</code>.
        </div>
      </div>
    </div>
  );
};
