import { useCallback, useEffect, useState } from 'react';
import { apiClient, type FileEntryView } from '../../api/client';
import { C } from '../theme';
import { WindowFrame, WindowNotice } from '../WindowFrame';
import { relativeTime } from './NotesWindow';
import type { WindowView } from '../useWindows';

/**
 * Dosyalar penceresi — çalışma kökünün SALT OKUNUR gezgini.
 *
 * Gördüğü ağaç, ajanın dosya araçlarının görebildiği ağacın aynısıdır:
 * ikisi de aynı `PathGuard`'dan geçer. Bu kasıtlıdır — kullanıcı "ajan
 * neye erişebiliyor?" sorusunu bu pencereye bakarak cevaplayabilmeli.
 *
 * Silme ve yazma yok. Bir tarayıcı penceresinden gelen isteğin dosya
 * silebilmesi, kazanılan kolaylığa değmezdi.
 */

interface Props {
  win: WindowView;
}

export const FilesWindow = ({ win }: Props) => {
  const [path, setPath] = useState('');
  const [parent, setParent] = useState<string | null>(null);
  const [entries, setEntries] = useState<FileEntryView[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [disabled, setDisabled] = useState(false);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async (target: string) => {
    setLoading(true);
    try {
      const result = await apiClient.listFiles(target);
      setEntries(result.entries);
      setParent(result.parent);
      setPath(result.path);
      setError(null);
      setDisabled(false);
    } catch (cause: unknown) {
      const message = cause instanceof Error ? cause.message : 'Klasör okunamadı.';
      // Çalışma kökü ayarlanmamışsa bu bir hata değil, kapalı bir
      // yetenektir; kullanıcıya kırmızı bir hata göstermek yanlış teşhis
      // olurdu.
      setDisabled(message.includes('Çalışma kökü'));
      setError(message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(''); }, [load]);

  return (
    <WindowFrame
      win={win}
      title="Dosyalar"
      background="rgba(15,18,25,.92)"
      toolbar={
        <span style={{ fontSize: 10.5, color: C.faint, maxWidth: 190, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {path || 'kök'}
        </span>
      }
    >
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
        {disabled ? (
          <WindowNotice>
            Çalışma kökü ayarlanmamış. Ajanın hangi klasörde çalışacağını
            belirleyene kadar dosya gezgini kapalı kalır.
          </WindowNotice>
        ) : error ? (
          <WindowNotice>
            <span style={{ color: '#f1798f' }}>{error}</span>
          </WindowNotice>
        ) : (
          <>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '9px 14px', fontSize: 10.5, letterSpacing: '.06em', color: C.faint, borderBottom: `1px solid ${C.lineSoft}` }}>
              <button
                onClick={() => parent !== null && void load(parent)}
                disabled={parent === null}
                style={{
                  background: 'transparent', border: 'none', fontFamily: 'inherit',
                  fontSize: 12, padding: 0,
                  color: parent === null ? 'rgba(232,236,244,.16)' : C.dim,
                  cursor: parent === null ? 'default' : 'pointer',
                }}
              >
                ← üst klasör
              </button>
              <span style={{ marginLeft: 'auto' }}>Değiştirilme</span>
            </div>

            <div style={{ flex: 1, overflow: 'auto', minHeight: 0 }}>
              {loading ? (
                <div style={{ padding: 14, fontSize: 12, color: C.faint }}>Yükleniyor...</div>
              ) : entries.length === 0 ? (
                <div style={{ padding: 14, fontSize: 12, color: C.faint }}>Bu klasör boş.</div>
              ) : (
                entries.map((entry) => (
                  <button
                    key={entry.path}
                    onClick={() => entry.is_dir && void load(entry.path)}
                    style={{
                      display: 'flex', alignItems: 'center', gap: 10, width: '100%',
                      padding: '8px 14px', border: 'none', background: 'transparent',
                      textAlign: 'left', fontFamily: 'inherit',
                      cursor: entry.is_dir ? 'pointer' : 'default',
                    }}
                  >
                    <span
                      style={{
                        width: 19, height: 15, flex: 'none', borderRadius: 3,
                        background: entry.is_dir
                          ? 'rgba(190,205,235,.55)'
                          : 'rgba(200,225,235,.35)',
                      }}
                    />
                    <span style={{ flex: 1, minWidth: 0 }}>
                      <span style={{ display: 'block', fontSize: 12.5, color: 'rgba(232,236,244,.88)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                        {entry.name}
                      </span>
                      <span style={{ display: 'block', fontSize: 10, color: C.faint }}>
                        {entry.is_dir ? 'Klasör' : formatSize(entry.size_bytes)}
                      </span>
                    </span>
                    <span style={{ fontSize: 11, color: C.dimmer, whiteSpace: 'nowrap' }}>
                      {entry.modified_at ? relativeTime(entry.modified_at) : ''}
                    </span>
                  </button>
                ))
              )}
            </div>
          </>
        )}
      </div>
    </WindowFrame>
  );
};

function formatSize(bytes: number | null): string {
  if (bytes === null) return '';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
