import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { apiClient, type NoteView } from '../../api/client';
import { appendItem, parseChecklist, toggleLine } from '../checklist';
import { C } from '../theme';
import { WindowFrame, WindowNotice } from '../WindowFrame';
import type { WindowView } from '../useWindows';

/**
 * Notlar penceresi — tasarımdaki iki sütunlu düzen, GERÇEK notlarla.
 *
 * Kaydetme GECİKTİRİLİR: her tuşta bir PUT göndermek, tek bir cümle için
 * onlarca yazma isteği demek olurdu. Ama gecikme "belki kaydedilir"
 * anlamına gelmemeli, bu yüzden pencere kapanırken ve not değiştirilirken
 * bekleyen yazma zorla akıtılır.
 *
 * Ajan da not yazabilir (`created_by === 'agent'`). Bu ayrım listede
 * gösterilir: ajanın yazdığı bir not onun O ANKİ anlayışını taşır ve
 * yanlış olabilir; kullanıcı kendi yazdığıyla karıştırmamalıdır.
 */

const SAVE_DELAY_MS = 700;

interface Props {
  win: WindowView;
  /** Ajan bir not yazdığında liste tazelensin diye artan sayaç. */
  refreshKey: number;
}

export const NotesWindow = ({ win, refreshKey }: Props) => {
  const [notes, setNotes] = useState<NoteView[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [draft, setDraft] = useState('');
  const [title, setTitle] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [editing, setEditing] = useState(false);

  const saveTimer = useRef<number | undefined>(undefined);
  // Bekleyen yazmanın hedefi. `selectedId` kullanılamaz: kullanıcı not
  // değiştirdiğinde bekleyen yazma ESKİ nota aitti ve yeni notun üzerine
  // yazılırdı.
  const pending = useRef<{ id: string; content: string; title: string } | null>(null);

  const load = useCallback(async () => {
    try {
      const result = await apiClient.getNotes();
      setNotes(result.notes);
      setError(null);
      setSelectedId((current) =>
        current && result.notes.some((note) => note.id === current)
          ? current
          : (result.notes[0]?.id ?? null),
      );
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : 'Notlar okunamadı.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load, refreshKey]);

  const selected = useMemo(
    () => notes.find((note) => note.id === selectedId) ?? null,
    [notes, selectedId],
  );

  // Seçim değiştiğinde taslak sunucudaki hâle döner. Yazmakta olan
  // kullanıcının metni ezilmesin diye `editing` bayrağı kontrol edilir.
  useEffect(() => {
    if (!selected) {
      setDraft('');
      setTitle('');
      return;
    }
    setDraft(selected.content);
    setTitle(selected.title);
    setEditing(false);
  }, [selected]);

  const flush = useCallback(async () => {
    const job = pending.current;
    if (!job) return;
    pending.current = null;
    window.clearTimeout(saveTimer.current);
    setSaving(true);
    try {
      const saved = await apiClient.updateNote(job.id, job.content, job.title);
      setNotes((current) => current.map((note) => (note.id === saved.id ? saved : note)));
      setError(null);
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : 'Not kaydedilemedi.');
    } finally {
      setSaving(false);
    }
  }, []);

  const queueSave = useCallback(
    (content: string, nextTitle: string) => {
      if (!selectedId) return;
      pending.current = { id: selectedId, content, title: nextTitle };
      window.clearTimeout(saveTimer.current);
      saveTimer.current = window.setTimeout(() => void flush(), SAVE_DELAY_MS);
    },
    [flush, selectedId],
  );

  // Pencere kaybolurken bekleyen yazma akıtılır; aksi hâlde son cümle
  // sessizce kaybolurdu.
  useEffect(() => () => { void flush(); }, [flush]);

  const items = useMemo(() => parseChecklist(draft), [draft]);

  const toggle = (line: number) => {
    const next = toggleLine(draft, line);
    setDraft(next);
    queueSave(next, title);
  };

  const addItem = async () => {
    if (!selectedId) return;
    const next = appendItem(draft, 'Yeni madde');
    setDraft(next);
    queueSave(next, title);
  };

  const create = async () => {
    try {
      const note = await apiClient.createNote('- [ ] Yeni madde', 'Yeni not');
      setNotes((current) => [note, ...current]);
      setSelectedId(note.id);
      setError(null);
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : 'Not oluşturulamadı.');
    }
  };

  const remove = async () => {
    if (!selectedId) return;
    const id = selectedId;
    pending.current = null;
    window.clearTimeout(saveTimer.current);
    try {
      await apiClient.deleteNote(id);
      setNotes((current) => current.filter((note) => note.id !== id));
      setSelectedId(null);
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : 'Not silinemedi.');
    }
  };

  return (
    <WindowFrame
      win={win}
      title="Notlar"
      toolbar={
        <span style={{ fontSize: 10.5, color: saving ? C.dim : 'transparent' }}>
          kaydediliyor...
        </span>
      }
    >
      <div style={{ width: 196, flex: 'none', borderRight: `1px solid ${C.lineSoft}`, display: 'flex', flexDirection: 'column' }}>
        <div style={{ flex: 1, overflow: 'auto', padding: '10px 8px' }}>
          {loading ? (
            <div style={{ fontSize: 12, color: C.faint, padding: 8 }}>Yükleniyor...</div>
          ) : notes.length === 0 ? (
            <div style={{ fontSize: 12, color: C.faint, padding: 8, lineHeight: 1.6 }}>
              Henüz not yok.
            </div>
          ) : (
            notes.map((note) => (
              <button
                key={note.id}
                onClick={() => { void flush(); setSelectedId(note.id); }}
                style={{
                  display: 'block', width: '100%', textAlign: 'left',
                  padding: '9px 11px', marginBottom: 2, borderRadius: 9, border: 'none',
                  cursor: 'pointer', fontFamily: 'inherit',
                  background: note.id === selectedId ? C.active : 'transparent',
                }}
              >
                <div style={{ fontSize: 13, color: 'rgba(232,236,244,.90)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                  {note.title || 'Başlıksız'}
                </div>
                <div style={{ marginTop: 3, fontSize: 11, color: C.faint }}>
                  {relativeTime(note.updated_at)}
                  {note.created_by === 'agent' ? ' · ajan' : ''}
                </div>
              </button>
            ))
          )}
        </div>
        <button
          onClick={() => void create()}
          style={{
            flex: 'none', height: 34, margin: 8, borderRadius: 9, cursor: 'pointer',
            border: `1px solid ${C.line}`, background: 'rgba(255,255,255,.045)',
            color: C.dim, fontSize: 12, fontFamily: 'inherit',
          }}
        >
          + Yeni not
        </button>
      </div>

      <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column' }}>
        {error ? (
          <div style={{ padding: '10px 16px', fontSize: 11.5, color: '#f1798f', borderBottom: `1px solid ${C.lineSoft}` }}>
            {error}
          </div>
        ) : null}

        {!selected ? (
          <WindowNotice>Soldan bir not seçin ya da yeni bir tane oluşturun.</WindowNotice>
        ) : (
          <>
            <div style={{ height: 40, flex: 'none', display: 'flex', alignItems: 'center', gap: 14, padding: '0 16px', borderBottom: `1px solid ${C.lineSoft}`, fontSize: 12.5, color: C.dimmer }}>
              <button onClick={() => setEditing((value) => !value)} style={toolButton}>
                {editing ? 'Liste' : 'Metin'}
              </button>
              <button onClick={() => void addItem()} style={toolButton}>+ madde</button>
              <button onClick={() => void remove()} style={{ ...toolButton, marginLeft: 'auto', color: 'rgba(241,121,143,.85)' }}>
                Sil
              </button>
            </div>

            <div style={{ flex: 1, padding: '18px 20px', overflow: 'auto', minHeight: 0 }}>
              <input
                value={title}
                onChange={(event) => { setTitle(event.target.value); queueSave(draft, event.target.value); }}
                placeholder="Başlıksız"
                style={{
                  width: '100%', border: 'none', outline: 'none', background: 'transparent',
                  fontSize: 21, fontWeight: 500, letterSpacing: '-.01em', color: C.textBright,
                  fontFamily: 'inherit', padding: 0,
                }}
              />

              {editing || items.length === 0 ? (
                <textarea
                  value={draft}
                  onChange={(event) => { setDraft(event.target.value); queueSave(event.target.value, title); }}
                  placeholder={'Notu yazın.\n"- [ ] " ile başlayan satırlar işaretlenebilir maddeye dönüşür.'}
                  style={{
                    marginTop: 16, width: '100%', minHeight: 200, border: 'none', outline: 'none',
                    background: 'transparent', resize: 'none', color: 'rgba(232,236,244,.86)',
                    fontSize: 14, lineHeight: 1.7, fontFamily: 'inherit', padding: 0,
                  }}
                />
              ) : (
                <div style={{ marginTop: 18, display: 'flex', flexDirection: 'column', gap: 13 }}>
                  {items.map((item) => (
                    <button
                      key={item.line}
                      onClick={() => toggle(item.line)}
                      style={{
                        display: 'flex', alignItems: 'center', gap: 12, cursor: 'pointer',
                        background: 'transparent', border: 'none', padding: 0,
                        textAlign: 'left', fontFamily: 'inherit',
                      }}
                    >
                      <span
                        style={{
                          width: 17, height: 17, flex: 'none', borderRadius: '50%',
                          border: '1.5px solid rgba(232,236,244,.30)',
                          display: 'flex', alignItems: 'center', justifyContent: 'center',
                          background: item.done ? 'rgba(190,215,255,.92)' : 'transparent',
                        }}
                      >
                        {item.done ? (
                          <span style={{ fontSize: 10, color: '#0b1220', fontWeight: 700 }}>✓</span>
                        ) : null}
                      </span>
                      <span
                        style={{
                          fontSize: 14,
                          color: item.done ? 'rgba(232,236,244,.34)' : 'rgba(232,236,244,.88)',
                          textDecoration: item.done ? 'line-through' : 'none',
                        }}
                      >
                        {item.text}
                      </span>
                    </button>
                  ))}
                </div>
              )}
            </div>
          </>
        )}
      </div>
    </WindowFrame>
  );
};

const toolButton: React.CSSProperties = {
  background: 'transparent',
  border: 'none',
  color: 'inherit',
  fontSize: 12,
  cursor: 'pointer',
  fontFamily: 'inherit',
  padding: 0,
};

/** "Bugün, 22:41" biçimi — tasarımdaki gösterimin aynısı. */
export function relativeTime(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '';

  const time = date.toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit' });
  const today = new Date();
  const sameDay = (a: Date, b: Date) =>
    a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();

  if (sameDay(date, today)) return `Bugün, ${time}`;
  const yesterday = new Date(today);
  yesterday.setDate(today.getDate() - 1);
  if (sameDay(date, yesterday)) return `Dün, ${time}`;

  return `${date.toLocaleDateString('tr-TR', { day: 'numeric', month: 'short' })}, ${time}`;
}
