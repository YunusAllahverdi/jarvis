import { useEffect, useRef } from 'react';
import { C } from './theme';
import type { ChatEntry } from './useConversation';

/**
 * Sohbet akışı.
 *
 * Üst kenar maskeyle söner: mesajlar başlığın altından çıkıyormuş gibi
 * görünsün diye. Sabit bir kesme çizgisi olsaydı, kaydırırken metin
 * keskin bir kenarda kesilir ve pencere daha küçük görünürdü.
 *
 * Otomatik kaydırma yalnızca kullanıcı ZATEN altta duruyorsa yapılır.
 * Koşulsuz kaydırmak, geçmişi okumak için yukarı çıkmış birini yeni
 * mesaj geldiğinde aşağı fırlatmak olurdu.
 */

interface Props {
  entries: ChatEntry[];
  busy: boolean;
}

export const ChatView = ({ entries, busy }: Props) => {
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const pinned = useRef(true);

  useEffect(() => {
    const node = scrollRef.current;
    if (!node || !pinned.current) return;
    node.scrollTop = node.scrollHeight;
  }, [entries, busy]);

  const onScroll = () => {
    const node = scrollRef.current;
    if (!node) return;
    pinned.current = node.scrollHeight - node.scrollTop - node.clientHeight < 60;
  };

  const mask =
    'linear-gradient(180deg, rgba(0,0,0,0) 0%, rgba(0,0,0,.25) 8%, rgba(0,0,0,.75) 20%, #000 34%, #000 100%)';

  return (
    <div
      ref={scrollRef}
      onScroll={onScroll}
      style={{
        position: 'absolute', left: 0, right: 0, top: 118, bottom: 150, zIndex: 40,
        display: 'flex', justifyContent: 'center', overflow: 'auto',
        maskImage: mask, WebkitMaskImage: mask,
      }}
    >
      <div style={{ width: 'min(760px,72vw)', display: 'flex', flexDirection: 'column', gap: 20, padding: '20px 0 40px' }}>
        {entries.length === 0 && !busy ? (
          <div style={{ marginTop: 60, textAlign: 'center', fontSize: 13.5, lineHeight: 1.7, color: C.faint }}>
            Bir şey sorun. Jarvis notlarınıza yazabilir, masadaki pencereleri
            açabilir ve izin verdiğiniz araçları kullanabilir.
          </div>
        ) : null}

        {entries.map((entry) =>
          entry.role === 'user' ? (
            <div key={entry.id} style={{ display: 'flex', justifyContent: 'flex-end' }}>
              <div
                style={{
                  maxWidth: '76%', padding: '13px 17px',
                  borderRadius: '18px 18px 6px 18px',
                  border: `1px solid ${C.line}`, background: 'rgba(255,255,255,.075)',
                  fontSize: 14.5, lineHeight: 1.6, color: C.textBright,
                  animation: 'deskFadeUp .22s ease both', whiteSpace: 'pre-wrap',
                }}
              >
                {entry.text}
              </div>
            </div>
          ) : (
            <div key={entry.id} style={{ display: 'flex', gap: 14, alignItems: 'flex-start', animation: 'deskFadeUp .22s ease both' }}>
              <span
                style={{
                  width: 22, height: 22, flex: 'none', marginTop: 3, borderRadius: '50%',
                  background: entry.failed
                    ? 'radial-gradient(circle at 34% 28%, rgba(255,190,200,.85), rgba(224,82,74,.45) 60%, rgba(20,24,32,.9))'
                    : 'radial-gradient(circle at 34% 28%, rgba(255,255,255,.85), rgba(160,190,240,.30) 55%, rgba(20,24,32,.9))',
                  boxShadow: '0 0 14px rgba(150,190,255,.35)',
                }}
              />
              <div
                style={{
                  fontSize: 14.5, lineHeight: 1.75, whiteSpace: 'pre-wrap',
                  color: entry.failed ? 'rgba(241,121,143,.92)' : 'rgba(232,236,244,.86)',
                }}
              >
                {entry.text}
              </div>
            </div>
          ),
        )}

        {busy ? (
          <div style={{ display: 'flex', gap: 14, alignItems: 'center' }}>
            <span
              style={{
                width: 22, height: 22, flex: 'none', borderRadius: '50%',
                background: 'radial-gradient(circle at 34% 28%, rgba(255,255,255,.85), rgba(160,190,240,.30) 55%, rgba(20,24,32,.9))',
                boxShadow: '0 0 14px rgba(150,190,255,.35)',
              }}
            />
            <span style={{ fontSize: 13, color: C.faint }}>düşünüyor...</span>
          </div>
        ) : null}
      </div>
    </div>
  );
};
