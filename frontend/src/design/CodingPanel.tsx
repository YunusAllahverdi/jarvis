import { useCallback, useState } from 'react';
import { apiClient, type CodingResult, type CodingStatus } from '../api/client';

/**
 * Kodlama döngüsünün çalıştırıldığı ve sonucunun okunduğu panel.
 *
 * BURADAKİ EN ÖNEMLİ KARAR RENKLERDE: backend "doğrulanmadı" ile "doğrulandı"
 * durumlarını ayrı tutuyor ve arayüz bu ayrımı KORUMAK ZORUNDA. İkisi de yeşil
 * gösterilseydi, backend'in kendine yasakladığı şeyi — kazanılmamış bir başarı
 * iddiasını — arayüz kullanıcıya yapmış olurdu.
 *
 * Bu yüzden yalnızca `completed` yeşildir. `applied_unverified` bilinçli olarak
 * sarıdır: değişiklik uygulandı ama arkasında hiçbir kanıt yok.
 */

const PANEL: React.CSSProperties = {
  borderRadius: 15,
  background: 'rgba(14,13,32,0.92)',
  border: '1px solid rgba(140,150,255,0.18)',
  backdropFilter: 'blur(20px)',
};

const MONO = "'JetBrains Mono', ui-monospace, monospace";

const FIELD: React.CSSProperties = {
  flex: 1,
  height: 40,
  padding: '0 14px',
  borderRadius: 10,
  background: 'rgba(140,150,255,0.06)',
  border: '1px solid rgba(140,150,255,0.16)',
  color: '#dfe2ff',
  fontSize: 13,
  fontFamily: 'inherit',
  outline: 'none',
};

interface StatusStyle {
  label: string;
  color: string;
  background: string;
  /** Durumun ne anlama geldiğini açıkça söyleyen tek cümle. */
  note: string;
}

const STATUS: Record<CodingStatus, StatusStyle> = {
  completed: {
    label: 'Tamamlandı',
    color: '#8fd9b6',
    background: 'rgba(74,222,155,0.14)',
    note: 'Değişiklik uygulandı ve doğrulama geçti.',
  },
  applied_unverified: {
    label: 'Doğrulanmadı',
    color: '#f0c675',
    background: 'rgba(240,198,117,0.14)',
    note: 'Değişiklik uygulandı, ancak doğrulama çalıştırılamadı — arkasında kanıt yok.',
  },
  verification_failed: {
    label: 'Doğrulama başarısız',
    color: '#f1798f',
    background: 'rgba(241,121,143,0.14)',
    note: 'Değişiklik uygulandı ama doğrulama tur sınırına rağmen geçmedi.',
  },
  pending_approval: {
    label: 'Onay bekliyor',
    color: '#b9a5ff',
    background: 'rgba(167,139,250,0.16)',
    note: 'Bir adım onay bekliyor; o adım ve sonrası çalıştırılmadı.',
  },
  no_plan: {
    label: 'Plan yok',
    color: '#9aa4cc',
    background: 'rgba(140,150,255,0.10)',
    note: 'Uygulanabilir bir adım üretilemedi.',
  },
  failed: {
    label: 'Başarısız',
    color: '#f1798f',
    background: 'rgba(241,121,143,0.14)',
    note: 'Döngü ilerleyemedi.',
  },
};

interface Props {
  onClose: () => void;
  sessionId: string | null;
}

export const CodingPanel = ({ onClose, sessionId }: Props) => {
  const [request, setRequest] = useState('');
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<CodingResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showDiff, setShowDiff] = useState(false);

  const run = useCallback(async () => {
    const text = request.trim();
    if (!text || busy) return;

    setBusy(true);
    setError(null);
    setResult(null);
    setShowDiff(false);
    try {
      setResult(await apiClient.runCoding(text, sessionId));
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Kodlama döngüsü çalıştırılamadı.');
    } finally {
      setBusy(false);
    }
  }, [request, busy, sessionId]);

  const status = result ? STATUS[result.status] : null;

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
        aria-label="Kodlama ajanı"
        style={{
          ...PANEL, width: 720, maxHeight: 780, padding: 22,
          display: 'flex', flexDirection: 'column', gap: 16,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div>
            <div style={{ fontSize: 14, fontWeight: 500, color: '#dfe2ff' }}>Kodlama Ajanı</div>
            <div style={{ fontSize: 11, color: '#8b96c8', marginTop: 3 }}>
              anla → planla → uygula → doğrula → düzelt
            </div>
          </div>
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

        <div style={{ display: 'flex', gap: 8 }}>
          <input
            value={request}
            onChange={(event) => setRequest(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') { event.preventDefault(); void run(); }
            }}
            placeholder="ör. add() fonksiyonundaki işaret hatasını düzelt"
            disabled={busy}
            aria-label="Kodlama isteği"
            style={FIELD}
          />
          <button
            onClick={() => void run()}
            disabled={busy || !request.trim()}
            style={{
              height: 40, padding: '0 20px', borderRadius: 11,
              cursor: busy || !request.trim() ? 'default' : 'pointer',
              background: request.trim() && !busy ? 'rgba(124,92,255,0.30)' : 'rgba(140,150,255,0.08)',
              border: '1px solid rgba(170,150,255,0.45)',
              color: '#dfe0ff', fontSize: 13, fontFamily: 'inherit', whiteSpace: 'nowrap',
            }}
          >
            {busy ? 'Çalışıyor...' : 'Çalıştır'}
          </button>
        </div>

        {busy && (
          <div style={{ fontSize: 12.5, color: '#8b96c8', lineHeight: 1.6 }}>
            Depo okunuyor, plan üretiliyor ve doğrulama çalıştırılıyor. Bu birkaç
            tur sürebilir.
          </div>
        )}

        {error && (
          <div role="status" style={{ fontSize: 12.5, color: '#f1798f', lineHeight: 1.55 }}>
            {error}
          </div>
        )}

        {result && status && (
          <div style={{ overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 14, paddingRight: 4 }}>
            {/* ── durum ── */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <span style={{
                  fontSize: 11.5, padding: '4px 10px', borderRadius: 7,
                  background: status.background, color: status.color, fontWeight: 500,
                }}>
                  {status.label}
                </span>
                {result.task?.verification_command && (
                  <span style={{ fontSize: 11, color: '#8b96c8', fontFamily: MONO }}>
                    {result.task.verification_command}
                  </span>
                )}
              </div>
              <div style={{ fontSize: 12, color: '#9aa4cc', lineHeight: 1.55 }}>{status.note}</div>
            </div>

            {result.task?.goal && (
              <Section title="Hedef">
                <div style={{ fontSize: 12.5, color: '#d3d8ff', lineHeight: 1.6 }}>
                  {result.task.goal}
                </div>
              </Section>
            )}

            {/* ── turlar ── */}
            {result.iterations.length > 0 && (
              <Section title={`Turlar (${result.iterations.length})`}>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
                  {result.iterations.map((iteration) => (
                    <div key={iteration.index} style={{ display: 'flex', flexDirection: 'column', gap: 7 }}>
                      <div style={{ fontSize: 11, color: '#8b96c8', fontFamily: MONO }}>
                        Tur {iteration.index + 1}
                      </div>
                      {iteration.outcomes.map((outcome, i) => {
                        const target = outcome.arguments.path ?? outcome.arguments.command;
                        const mark = outcome.skipped
                          ? { text: 'atlandı', color: '#8b96c8' }
                          : outcome.success
                            ? { text: 'tamam', color: '#8fd9b6' }
                            : outcome.requires_approval
                              ? { text: 'onay bekliyor', color: '#b9a5ff' }
                              : { text: outcome.error_code ?? 'başarısız', color: '#f1798f' };
                        return (
                          <div
                            key={`${outcome.tool_name}-${i}`}
                            style={{
                              display: 'flex', alignItems: 'center', gap: 10,
                              fontSize: 12, fontFamily: MONO, color: '#aeb7e2',
                            }}
                          >
                            <span style={{ color: '#d3d8ff' }}>{outcome.tool_name}</span>
                            {typeof target === 'string' && target && (
                              <span style={{ color: '#7a85b5', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                {target}
                              </span>
                            )}
                            <span style={{ color: mark.color, marginLeft: 'auto' }}>{mark.text}</span>
                          </div>
                        );
                      })}
                      {iteration.verification && (
                        <div style={{ fontSize: 11.5, color: '#8b96c8', lineHeight: 1.5, marginTop: 2 }}>
                          {iteration.verification.ran
                            ? iteration.verification.passed
                              ? 'Doğrulama geçti.'
                              : `Doğrulama başarısız${
                                  iteration.verification.timed_out
                                    ? ' (zaman aşımı)'
                                    : ` (çıkış kodu ${iteration.verification.exit_code})`
                                }.${
                                  iteration.verification.diagnosis
                                    ? ` ${iteration.verification.diagnosis.summary}`
                                    : ''
                                }`
                            : `Doğrulama çalışmadı: ${iteration.verification.skipped_reason ?? 'sebep bilinmiyor'}`}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </Section>
            )}

            {result.pending_approval_ids.length > 0 && (
              <Section title="Onay bekleyen istekler">
                <div style={{ fontSize: 12, color: '#b9a5ff', lineHeight: 1.6 }}>
                  {result.pending_approval_ids.length} istek onay bekliyor. Onaylamak
                  için <span style={{ fontFamily: MONO }}>/api/approvals</span> uçlarını
                  kullanın.
                </div>
              </Section>
            )}

            {/* ── diff ── */}
            {result.diff && (
              <Section title="Değişiklikler">
                <button
                  onClick={() => setShowDiff((open) => !open)}
                  style={{
                    alignSelf: 'flex-start', padding: '5px 12px', borderRadius: 8, cursor: 'pointer',
                    background: 'rgba(140,150,255,0.08)', border: '1px solid rgba(140,150,255,0.18)',
                    color: '#c3cbf6', fontSize: 11.5, fontFamily: 'inherit',
                  }}
                >
                  {showDiff ? 'Farkı gizle' : 'Farkı göster'}
                </button>
                {showDiff && (
                  <pre style={{
                    margin: '10px 0 0', padding: 12, borderRadius: 10, maxHeight: 260, overflow: 'auto',
                    background: 'rgba(4,3,12,0.6)', border: '1px solid rgba(140,150,255,0.12)',
                    fontFamily: MONO, fontSize: 11, lineHeight: 1.55, color: '#c3cbf6',
                    whiteSpace: 'pre', tabSize: 2,
                  }}>
                    {result.diff}
                  </pre>
                )}
              </Section>
            )}

            {/* Deterministik özet: backend'de üretiliyor, burada yeniden yazılmıyor. */}
            <Section title="Özet">
              <pre style={{
                margin: 0, fontFamily: 'inherit', fontSize: 12.5, lineHeight: 1.65,
                color: '#aeb7e2', whiteSpace: 'pre-wrap',
              }}>
                {result.summary}
              </pre>
            </Section>
          </div>
        )}
      </div>
    </div>
  );
};

const Section = ({ title, children }: { title: string; children: React.ReactNode }) => (
  <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
    <div style={{
      fontSize: 11, letterSpacing: '0.06em', textTransform: 'uppercase', color: '#8b96c8',
    }}>
      {title}
    </div>
    {children}
  </div>
);
