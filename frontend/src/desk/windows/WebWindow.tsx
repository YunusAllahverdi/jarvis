import { useState } from 'react';
import { apiClient, type FetchedPage } from '../../api/client';
import { C, MONO } from '../theme';
import { WindowFrame, WindowNotice } from '../WindowFrame';
import type { WindowView } from '../useWindows';

/**
 * Web penceresi — sayfaları OKUYAN bir okuyucu, tarayıcı değil.
 *
 * Neden `<iframe>` değil: sayfaların büyük çoğunluğu `X-Frame-Options`
 * ile gömülmeyi reddeder, gömülenler de aynı origin kuralları yüzünden
 * okunamaz. Bir tarayıcı taklidi, sayfaların çoğunda boş bir kutu
 * olarak kalırdı.
 *
 * Bunun yerine sayfa sunucudan geçirilir ve METNİ gösterilir. Ajanın
 * `fetch_url` aracıyla aynı bekçiden geçtiği için, kullanıcının burada
 * bakabildiği yer ile ajanın bakabildiği yer aynıdır.
 */

const SHORTCUTS = [
  { label: 'Python', url: 'https://docs.python.org/3/' },
  { label: 'MDN', url: 'https://developer.mozilla.org/' },
  { label: 'FastAPI', url: 'https://fastapi.tiangolo.com/' },
  { label: 'React', url: 'https://react.dev/' },
];

interface Props {
  win: WindowView;
}

export const WebWindow = ({ win }: Props) => {
  const [address, setAddress] = useState('');
  const [page, setPage] = useState<FetchedPage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [disabled, setDisabled] = useState(false);
  const [loading, setLoading] = useState(false);

  const go = async (url: string) => {
    const target = url.trim();
    if (!target) return;
    setAddress(target);
    setLoading(true);
    try {
      const result = await apiClient.fetchPage(
        // Protokolsüz yazılan adres, bekçide "desteklenmeyen şema" olarak
        // reddedilirdi; kullanıcının bunu bilmesi gerekmez.
        /^https?:\/\//i.test(target) ? target : `https://${target}`,
      );
      setPage(result);
      setError(null);
      setDisabled(false);
    } catch (cause: unknown) {
      const message = cause instanceof Error ? cause.message : 'Sayfa getirilemedi.';
      setDisabled(message.includes('Web erişimi kapalı'));
      setError(message);
      setPage(null);
    } finally {
      setLoading(false);
    }
  };

  return (
    <WindowFrame win={win} title="Web" background="rgba(14,17,24,.92)">
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
        <div style={{ height: 48, flex: 'none', display: 'flex', alignItems: 'center', gap: 10, padding: '0 14px' }}>
          <button
            onClick={() => { setPage(null); setError(null); }}
            title="Başlangıç"
            style={{ background: 'transparent', border: 'none', color: C.dimmer, fontSize: 15, cursor: 'pointer', padding: 0 }}
          >
            ←
          </button>
          <button
            onClick={() => void go(address)}
            title="Yenile"
            style={{ background: 'transparent', border: 'none', color: C.dimmer, fontSize: 14, cursor: 'pointer', padding: 0 }}
          >
            ⟳
          </button>
          <form
            onSubmit={(event) => { event.preventDefault(); void go(address); }}
            style={{ flex: 1, display: 'flex' }}
          >
            <input
              value={address}
              onChange={(event) => setAddress(event.target.value)}
              placeholder="Bir adres yazın..."
              style={{
                flex: 1, height: 32, borderRadius: 9, border: `1px solid rgba(255,255,255,.09)`,
                background: 'rgba(255,255,255,.045)', padding: '0 12px', outline: 'none',
                color: C.textBright, fontSize: 12.5, fontFamily: 'inherit',
              }}
            />
          </form>
        </div>

        <div style={{ flex: 1, minHeight: 0, overflow: 'auto', background: 'linear-gradient(180deg,#1b2027,#0d1015)' }}>
          {disabled ? (
            <WindowNotice>
              Web erişimi kapalı. Ayarlardan araştırmayı açtığınızda hem bu
              pencere hem de ajan sayfa okuyabilir.
            </WindowNotice>
          ) : loading ? (
            <WindowNotice>Getiriliyor...</WindowNotice>
          ) : error ? (
            <WindowNotice><span style={{ color: '#f1798f' }}>{error}</span></WindowNotice>
          ) : page ? (
            <div style={{ padding: '22px 26px' }}>
              <div style={{ fontSize: 19, fontWeight: 400, lineHeight: 1.3, color: C.textBright }}>
                {page.title || page.url}
              </div>
              <div style={{ marginTop: 6, fontSize: 11, color: C.faint, fontFamily: MONO, wordBreak: 'break-all' }}>
                {page.url} · {page.status_code}
              </div>
              {page.redirected_to ? (
                <div style={{ marginTop: 14, fontSize: 12, color: C.dim, lineHeight: 1.6 }}>
                  Bu adres başka bir yere yönlendiriyor. Yönlendirme izlenmedi —
                  denetlenen adresle getirilen adres ayrışmasın diye.
                  <button
                    onClick={() => void go(page.redirected_to as string)}
                    style={{ marginLeft: 8, background: 'transparent', border: `1px solid ${C.line}`, borderRadius: 7, padding: '4px 9px', color: C.text, fontSize: 11.5, cursor: 'pointer', fontFamily: 'inherit' }}
                  >
                    Yeni adrese git
                  </button>
                </div>
              ) : (
                <div style={{ marginTop: 18, fontSize: 13, lineHeight: 1.75, color: 'rgba(232,236,244,.80)', whiteSpace: 'pre-wrap' }}>
                  {page.content}
                  {page.truncated ? (
                    <div style={{ marginTop: 16, fontSize: 11.5, color: C.faint }}>
                      — Sayfa uzun olduğu için kırpıldı.
                    </div>
                  ) : null}
                </div>
              )}
            </div>
          ) : (
            <div style={{ position: 'relative', height: '100%', minHeight: 240 }}>
              <div style={{ position: 'absolute', left: 34, top: 60, fontSize: 27, lineHeight: 1.28, color: C.textBright }}>
                Daha fazlasını<br />keşfet.
              </div>
              <div style={{ position: 'absolute', left: 34, right: 34, bottom: 26, display: 'flex', gap: 12 }}>
                {SHORTCUTS.map((shortcut) => (
                  <button
                    key={shortcut.label}
                    onClick={() => void go(shortcut.url)}
                    style={{
                      flex: 1, height: 74, borderRadius: 11, cursor: 'pointer',
                      border: '1px solid rgba(255,255,255,.09)', background: 'rgba(255,255,255,.05)',
                      display: 'flex', flexDirection: 'column', alignItems: 'center',
                      justifyContent: 'center', gap: 8, fontFamily: 'inherit',
                    }}
                  >
                    <span style={{ width: 22, height: 22, borderRadius: 6, background: 'rgba(232,236,244,.80)' }} />
                    <span style={{ fontSize: 10.5, color: 'rgba(232,236,244,.66)' }}>{shortcut.label}</span>
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </WindowFrame>
  );
};
