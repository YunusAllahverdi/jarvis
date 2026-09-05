import { useCallback, useEffect, useState } from 'react';
import { Desk } from './desk/Desk';
import { TokenGate } from './design/TokenGate';
import { AuthRequiredError, apiClient } from './api/client';

/**
 * Kabuğun önündeki kimlik kapısı.
 *
 * Kapı yalnızca sunucu GERÇEKTEN anahtar istediğinde belirir. Yerelde
 * çalışan kullanıcı için anahtar gerekmiyor ve ona her açılışta bir giriş
 * ekranı göstermek, olmayan bir engel uydurmak olurdu.
 *
 * Bu yüzden açılışta kimlik gerektiren, yan etkisiz bir uç bir kez denenir:
 * geçerse kabuk açılır, 401/403 dönerse kapı çıkar. Başka bir hata (sunucu
 * kapalı) kapıyı AÇMAZ — o durumda anahtar istemek yanlış teşhis olurdu ve
 * kullanıcı çalışmayan bir şeye anahtar aramaya başlardı.
 */

type Status = 'checking' | 'ready' | 'needs-token';

function App() {
  const [status, setStatus] = useState<Status>('checking');
  const [message, setMessage] = useState<string | undefined>();

  const probe = useCallback(async () => {
    try {
      await apiClient.getSystemStatus();
      setStatus('ready');
    } catch (error: unknown) {
      if (error instanceof AuthRequiredError) {
        setMessage(error.message);
        setStatus('needs-token');
        return;
      }
      // Sunucuya ulaşılamıyor ya da başka bir hata: kabuk yine açılır ve
      // hatayı kendi yüzeyinde gösterir. Kapıyı açmak yanlış teşhis olurdu.
      setStatus('ready');
    }
  }, []);

  useEffect(() => { void probe(); }, [probe]);

  if (status === 'checking') {
    return (
      <div style={{
        position: 'fixed', inset: 0, background: '#04030c',
        display: 'grid', placeItems: 'center',
        color: '#8b96c8', fontFamily: 'Sora, Helvetica, sans-serif', fontSize: 13,
      }}>
        Bağlanıyor...
      </div>
    );
  }

  if (status === 'needs-token') {
    return <TokenGate message={message} onAuthorized={() => setStatus('ready')} />;
  }

  return <Desk />;
}

export default App;
