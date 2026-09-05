import { useCallback, useEffect, useMemo, useState } from 'react';
import { apiClient, type NoteView } from '../../api/client';
import { parseChecklist, toggleLine } from '../checklist';
import { C } from '../theme';
import { WindowFrame, WindowNotice } from '../WindowFrame';
import type { WindowView } from '../useWindows';

/**
 * Görevler penceresi — bütün notlardaki maddelerin tek listesi.
 *
 * Görevler için AYRI bir depo yok. Bir görev zaten bir notun bir
 * satırıdır; ikinci bir tablo, aynı maddenin iki yerde yaşaması ve
 * birinin diğerinden haberi olmaması demek olurdu. Bu pencere yalnızca
 * başka bir bakış açısıdır: not bazlı değil, madde bazlı.
 *
 * İşaretlemek gerçekten kaynak notu değiştirir; Notlar penceresi açıksa
 * orada da işaretli görünür.
 */

type Tab = 'Bugün' | 'Bu Hafta' | 'Tümü';

const TABS: Tab[] = ['Bugün', 'Bu Hafta', 'Tümü'];

interface Row {
  noteId: string;
  noteTitle: string;
  line: number;
  text: string;
  done: boolean;
}

interface Props {
  win: WindowView;
  refreshKey: number;
}

export const TasksWindow = ({ win, refreshKey }: Props) => {
  const [notes, setNotes] = useState<NoteView[]>([]);
  const [tab, setTab] = useState<Tab>('Bugün');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      const result = await apiClient.getNotes();
      setNotes(result.notes);
      setError(null);
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : 'Görevler okunamadı.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load, refreshKey]);

  const rows = useMemo<Row[]>(() => {
    const now = Date.now();
    // Sekmeler, notun ne zaman GÜNCELLENDİĞİNE bakar. Bir maddenin kendi
    // tarihi yok; olsaydı biçimin içine tarih gömmek gerekirdi ve not
    // başka bir yerde okunduğunda anlamsız görünürdü.
    const withinDays = (iso: string, days: number) => {
      const time = new Date(iso).getTime();
      return Number.isFinite(time) && now - time <= days * 24 * 60 * 60 * 1000;
    };

    return notes
      .filter((note) => {
        if (tab === 'Tümü') return true;
        return withinDays(note.updated_at, tab === 'Bugün' ? 1 : 7);
      })
      .flatMap((note) =>
        parseChecklist(note.content).map((item) => ({
          noteId: note.id,
          noteTitle: note.title || 'Başlıksız',
          line: item.line,
          text: item.text,
          done: item.done,
        })),
      )
      .sort((a, b) => Number(a.done) - Number(b.done));
  }, [notes, tab]);

  const toggle = async (row: Row) => {
    const note = notes.find((item) => item.id === row.noteId);
    if (!note) return;
    const content = toggleLine(note.content, row.line);

    // İyimser güncelleme: tıklamayla işaretin görünmesi arasında bir ağ
    // gidiş-dönüşü kadar boşluk kalsaydı, kullanıcı tıklamanın işe
    // yaramadığını düşünüp ikinci kez tıklardı — ve maddeyi geri açardı.
    setNotes((current) =>
      current.map((item) => (item.id === note.id ? { ...item, content } : item)),
    );

    try {
      const saved = await apiClient.updateNote(note.id, content, note.title);
      setNotes((current) => current.map((item) => (item.id === saved.id ? saved : item)));
      setError(null);
    } catch (cause: unknown) {
      // Başarısızsa sunucudaki gerçek hâle dönülür; ekranda yalan kalmaz.
      setError(cause instanceof Error ? cause.message : 'Görev güncellenemedi.');
      void load();
    }
  };

  return (
    <WindowFrame win={win} title="Görevler" background="rgba(16,19,27,.92)">
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
        <div style={{ flex: 'none', display: 'flex', alignItems: 'center', gap: 8, padding: '10px 12px' }}>
          {TABS.map((name) => (
            <button
              key={name}
              onClick={() => setTab(name)}
              style={{
                padding: '6px 13px', borderRadius: 20, fontSize: 12, cursor: 'pointer',
                border: 'none', fontFamily: 'inherit',
                background: tab === name ? C.active : 'transparent',
                color: tab === name ? C.textBright : C.dim,
              }}
            >
              {name}
            </button>
          ))}
        </div>

        {error ? (
          <div style={{ padding: '0 14px 8px', fontSize: 11.5, color: '#f1798f' }}>{error}</div>
        ) : null}

        {loading ? (
          <WindowNotice>Yükleniyor...</WindowNotice>
        ) : rows.length === 0 ? (
          <WindowNotice>
            Bu aralıkta madde yok. Notlar penceresinde bir satırı
            {' "'}- [ ] {'"'} ile başlatın; burada görev olarak çıkar.
          </WindowNotice>
        ) : (
          <div style={{ flex: 1, padding: '0 12px 12px', overflow: 'auto', display: 'flex', flexDirection: 'column', gap: 11 }}>
            {rows.map((row) => (
              <button
                key={`${row.noteId}:${row.line}`}
                onClick={() => void toggle(row)}
                title={row.noteTitle}
                style={{
                  display: 'flex', alignItems: 'center', gap: 11, cursor: 'pointer',
                  background: 'transparent', border: 'none', padding: 0,
                  textAlign: 'left', fontFamily: 'inherit',
                }}
              >
                <span
                  style={{
                    width: 17, height: 17, flex: 'none', borderRadius: '50%',
                    border: '1.5px solid rgba(232,236,244,.28)',
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    background: row.done ? 'rgba(190,215,255,.92)' : 'transparent',
                  }}
                >
                  {row.done ? (
                    <span style={{ fontSize: 10, color: '#0b1220', fontWeight: 700 }}>✓</span>
                  ) : null}
                </span>
                <span
                  style={{
                    fontSize: 13, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                    color: row.done ? 'rgba(232,236,244,.32)' : 'rgba(232,236,244,.88)',
                    textDecoration: row.done ? 'line-through' : 'none',
                  }}
                >
                  {row.text}
                </span>
              </button>
            ))}
          </div>
        )}
      </div>
    </WindowFrame>
  );
};
