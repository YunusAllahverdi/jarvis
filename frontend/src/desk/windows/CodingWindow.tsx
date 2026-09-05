import { useState } from 'react';
import { apiClient, type CodingResult, type CodingStatus } from '../../api/client';
import { C, MONO } from '../theme';
import { WindowFrame, WindowNotice } from '../WindowFrame';
import type { WindowView } from '../useWindows';

/**
 * Kodlama döngüsü penceresi: anla → planla → uygula → doğrula → onar.
 *
 * Tasarımda böyle bir pencere yoktu; buraya eklendi çünkü döngü çalışan
 * bir yetenek ve arayüzsüz bırakılsaydı ulaşılamaz olurdu. Masa zaten
 * pencerelerden oluşan bir ortam; yeni bir yetenek yeni bir pencere
 * demek.
 *
 * BURADAKİ EN ÖNEMLİ KARAR RENKLERDE. Backend "uygulandı" ile
 * "doğrulandı"yı ayrı durumlar olarak tutuyor ve arayüz bu ayrımı
 * KORUMAK ZORUNDA: ikisi de yeşil gösterilseydi, backend'in kendine
 * yasakladığı şeyi — kazanılmamış bir başarı iddiasını — arayüz
 * kullanıcıya yapmış olurdu. Bu yüzden yalnızca `completed` yeşildir.
 */

interface Tone {
  label: string;
  color: string;
  note: string;
}

const STATUS: Record<CodingStatus, Tone> = {
  completed: {
    label: 'Tamamlandı',
    color: '#8fd9b6',
    note: 'Değişiklik uygulandı ve doğrulama geçti.',
  },
  applied_unverified: {
    label: 'Doğrulanmadı',
    color: '#f0c675',
    note: 'Değişiklik uygulandı ama doğrulama çalıştırılamadı — arkasında kanıt yok.',
  },
  verification_failed: {
    label: 'Doğrulama başarısız',
    color: '#f1798f',
    note: 'Değişiklik uygulandı ama doğrulama tur sınırına rağmen geçmedi.',
  },
  pending_approval: {
    label: 'Onay bekliyor',
    color: '#b9a5ff',
    note: 'Bir adım onay bekliyor; o adım ve sonrası çalıştırılmadı.',
  },
  no_plan: {
    label: 'Plan çıkmadı',
    color: '#9aa4cc',
    note: 'Model bir plan üretmedi; hiçbir dosyaya dokunulmadı.',
  },
  failed: {
    label: 'Başarısız',
    color: '#f1798f',
    note: 'Döngü tamamlanamadı.',
  },
};

interface Props {
  win: WindowView;
  sessionId: string | null;
}

export const CodingWindow = ({ win, sessionId }: Props) => {
  const [request, setRequest] = useState('');
  const [result, setResult] = useState<CodingResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const run = async () => {
    const text = request.trim();
    if (!text || busy) return;
    setBusy(true);
    setError(null);
    try {
      setResult(await apiClient.runCoding(text, sessionId));
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : 'Döngü çalıştırılamadı.');
      setResult(null);
    } finally {
      setBusy(false);
    }
  };

  const tone = result ? STATUS[result.status] : null;

  return (
    <WindowFrame win={win} title="Kodlama" background="rgba(14,17,26,.93)">
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
        <form
          onSubmit={(event) => { event.preventDefault(); void run(); }}
          style={{ flex: 'none', display: 'flex', gap: 8, padding: '12px 14px', borderBottom: `1px solid ${C.lineSoft}` }}
        >
          <input
            value={request}
            onChange={(event) => setRequest(event.target.value)}
            placeholder="ör. calc.py'daki bölme hatasını düzelt"
            disabled={busy}
            style={{
              flex: 1, height: 36, padding: '0 12px', borderRadius: 9,
              border: `1px solid ${C.line}`, background: 'rgba(255,255,255,.045)',
              color: C.textBright, fontSize: 12.5, fontFamily: 'inherit', outline: 'none',
            }}
          />
          <button
            type="submit"
            disabled={busy || !request.trim()}
            style={{
              height: 36, padding: '0 16px', borderRadius: 9,
              cursor: busy || !request.trim() ? 'default' : 'pointer',
              border: '1px solid rgba(170,150,255,.42)', background: 'rgba(124,92,255,.26)',
              color: '#dfe0ff', fontSize: 12.5, fontFamily: 'inherit',
              opacity: busy || !request.trim() ? 0.5 : 1,
            }}
          >
            {busy ? 'Çalışıyor...' : 'Çalıştır'}
          </button>
        </form>

        <div style={{ flex: 1, overflow: 'auto', minHeight: 0 }}>
          {error ? (
            <WindowNotice><span style={{ color: '#f1798f' }}>{error}</span></WindowNotice>
          ) : !result ? (
            <WindowNotice>
              Döngü dosyayı değiştirir, doğrulama komutunu çalıştırır ve
              geçmezse teşhis edip onarmayı dener. Kapalıysa uç 503 döner.
            </WindowNotice>
          ) : (
            <div style={{ padding: '14px 16px' }}>
              {tone ? (
                <>
                  <div style={{ fontSize: 13, color: tone.color }}>{tone.label}</div>
                  <div style={{ marginTop: 5, fontSize: 11.5, lineHeight: 1.6, color: C.dimmer }}>
                    {tone.note}
                  </div>
                </>
              ) : null}

              <div style={{ marginTop: 14, fontSize: 12.5, lineHeight: 1.7, color: 'rgba(232,236,244,.82)', whiteSpace: 'pre-wrap' }}>
                {result.summary}
              </div>

              {result.iterations.length > 0 ? (
                <div style={{ marginTop: 14, fontSize: 11.5, color: C.dimmer }}>
                  {result.iterations.length} tur
                  {result.task?.verification_command
                    ? ` · doğrulama: ${result.task.verification_command}`
                    : ' · doğrulama komutu yok'}
                </div>
              ) : null}

              {result.diff ? (
                <pre
                  style={{
                    marginTop: 14, padding: 12, borderRadius: 10, overflow: 'auto',
                    background: 'rgba(0,0,0,.32)', border: `1px solid ${C.lineSoft}`,
                    fontFamily: MONO, fontSize: 11, lineHeight: 1.55,
                    color: 'rgba(232,236,244,.78)',
                  }}
                >
                  {result.diff}
                </pre>
              ) : null}
            </div>
          )}
        </div>
      </div>
    </WindowFrame>
  );
};
