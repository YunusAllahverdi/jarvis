import { useCallback, useEffect, useState } from 'react';
import { apiClient, type NoteView } from '../api/client';

/**
 * Notlar paneli — kullanıcının ve ajanın paylaştığı kalıcı yüzey.
 *
 * İki karar burada görünür olmalı:
 *
 * 1. AJANIN YAZDIĞI NOT İŞARETLENİR. Ajanın yazdığı bir metin, o anki
 *    anlayışını taşır ve yanlış olabilir. Kullanıcının kendi yazdığıyla
 *    aynı görünseydi, yanlış bir notu kendi yazdığı sanabilirdi.
 * 2. SİLME ONAY İSTER. Silme kalıcıdır (bellek katmanının aksine mantıksal
 *    silme yoktur), bu yüzden tek tıkla olmaz.
 */

const PANEL: React.CSSProperties = {
  borderRadius: 15,
  background: 'rgba(14,13,32,0.92)',
  border: '1px solid rgba(140,150,255,0.18)',
  backdropFilter: 'blur(20px)',
};

const MONO = "'JetBrains Mono', ui-monospace, monospace";

const FIELD: React.CSSProperties = {
  width: '100%',
  padding: '10px 12px',
  borderRadius: 10,
  background: 'rgba(140,150,255,0.06)',
  border: '1px solid rgba(140,150,255,0.16)',
  color: '#dfe2ff',
  fontSize: 13,
  fontFamily: 'inherit',
  outline: 'none',
  boxSizing: 'border-box',
};

interface Props {
  onClose: () => void;
}

export const NotesPanel = ({ onClose }: Props) => {
  const [notes, setNotes] = useState<NoteView[]>([]);
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [draftTitle, setDraftTitle] = useState('');
  const [draftContent, setDraftContent] = useState('');
  const [editingId, setEditingId] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [confirmingDelete, setConfirmingDelete] = useState<string | null>(null);

  const load = useCallback(async (searchTerm = '') => {
    setLoading(true);
    setError(null);
    try {
      setNotes((await apiClient.getNotes(searchTerm)).notes);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Notlar okunamadı.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const resetDraft = useCallback(() => {
    setDraftTitle('');
    setDraftContent('');
    setEditingId(null);
  }, []);

  const save = useCallback(async () => {
    const content = draftContent.trim();
    if (!content || saving) return;

    setSaving(true);
    setError(null);
    try {
      if (editingId) {
        await apiClient.updateNote(editingId, content, draftTitle.trim());
      } else {
        await apiClient.createNote(content, draftTitle.trim());
      }
      resetDraft();
      await load(query);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Not kaydedilemedi.');
    } finally {
      setSaving(false);
    }
  }, [draftContent, draftTitle, editingId, saving, query, load, resetDraft]);

  const remove = useCallback(async (id: string) => {
    setError(null);
    try {
      await apiClient.deleteNote(id);
      setConfirmingDelete(null);
      if (editingId === id) resetDraft();
      await load(query);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Not silinemedi.');
    }
  }, [query, load, editingId, resetDraft]);

  const startEditing = useCallback((note: NoteView) => {
    setEditingId(note.id);
    setDraftTitle(note.title);
    setDraftContent(note.content);
  }, []);

  return (
    <div
      onClick={onClose}
      style={{
        position: 'absolute', inset: 0, zIndex: 20,
        background: 'rgba(4,3,12,0.55)', display: 'grid', placeItems: 'center',
      }}
    >
      <div
        onClick={(event) => event.stopPropagation()}
        role="dialog"
        aria-label="Notlar"
        style={{
          ...PANEL, width: 680, maxHeight: 760, padding: 22,
          display: 'flex', flexDirection: 'column', gap: 14,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div>
            <div style={{ fontSize: 14, fontWeight: 500, color: '#dfe2ff' }}>Notlar</div>
            <div style={{ fontSize: 11, color: '#8b96c8', marginTop: 3 }}>
              Sizin ve Jarvis'in paylaştığı kalıcı yüzey
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

        {/* ── yazma alanı ── */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <input
            value={draftTitle}
            onChange={(event) => setDraftTitle(event.target.value)}
            placeholder="Başlık (isteğe bağlı)"
            aria-label="Not başlığı"
            style={FIELD}
          />
          <textarea
            value={draftContent}
            onChange={(event) => setDraftContent(event.target.value)}
            placeholder="Not içeriği"
            aria-label="Not içeriği"
            rows={3}
            style={{ ...FIELD, resize: 'vertical', lineHeight: 1.5 }}
          />
          <div style={{ display: 'flex', gap: 8 }}>
            <button
              onClick={() => void save()}
              disabled={saving || !draftContent.trim()}
              style={{
                height: 36, padding: '0 18px', borderRadius: 10,
                cursor: saving || !draftContent.trim() ? 'default' : 'pointer',
                background: draftContent.trim() && !saving
                  ? 'rgba(124,92,255,0.30)'
                  : 'rgba(140,150,255,0.08)',
                border: '1px solid rgba(170,150,255,0.45)',
                color: '#dfe0ff', fontSize: 12.5, fontFamily: 'inherit',
              }}
            >
              {saving ? 'Kaydediliyor...' : editingId ? 'Güncelle' : 'Kaydet'}
            </button>
            {editingId && (
              <button
                onClick={resetDraft}
                style={{
                  height: 36, padding: '0 14px', borderRadius: 10, cursor: 'pointer',
                  background: 'transparent', border: '1px solid rgba(140,150,255,0.16)',
                  color: '#aab4e8', fontSize: 12.5, fontFamily: 'inherit',
                }}
              >
                Vazgeç
              </button>
            )}
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') { event.preventDefault(); void load(query); }
              }}
              placeholder="Notlarda ara"
              aria-label="Notlarda ara"
              style={{ ...FIELD, flex: 1, height: 36, padding: '0 12px' }}
            />
          </div>
        </div>

        {error && (
          <div role="status" style={{ fontSize: 12.5, color: '#f1798f', lineHeight: 1.55 }}>
            {error}
          </div>
        )}

        {/* ── liste ── */}
        <div style={{ overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 10, paddingRight: 4 }}>
          {loading && <Muted>Yükleniyor...</Muted>}
          {!loading && notes.length === 0 && (
            <Muted>
              {query.trim()
                ? 'Bu aramayla eşleşen not yok.'
                : 'Henüz not yok. Yukarıdan ilkini yazabilirsiniz.'}
            </Muted>
          )}
          {!loading && notes.map((note) => (
            <div
              key={note.id}
              style={{
                padding: 13, borderRadius: 11,
                background: 'rgba(140,150,255,0.05)',
                border: '1px solid rgba(140,150,255,0.12)',
                display: 'flex', flexDirection: 'column', gap: 7,
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10 }}>
                <div style={{ fontSize: 12.5, fontWeight: 500, color: '#dfe2ff' }}>
                  {note.title || 'Başlıksız'}
                </div>
                {/* Ajanın yazdığı not işaretlenir: o metin ajanın o anki
                    anlayışını taşır ve yanlış olabilir. */}
                {note.created_by === 'agent' && (
                  <span style={{
                    fontSize: 10, padding: '2px 7px', borderRadius: 6,
                    background: 'rgba(167,139,250,0.16)', color: '#b9a5ff', fontFamily: MONO,
                  }}>
                    Jarvis yazdı
                  </span>
                )}
              </div>
              <div style={{ fontSize: 12.5, color: '#d3d8ff', lineHeight: 1.55, whiteSpace: 'pre-wrap' }}>
                {note.content}
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 2 }}>
                <span style={{ fontSize: 10.5, fontFamily: MONO, color: '#7a85b5', flex: 1 }}>
                  {new Date(note.updated_at).toLocaleString('tr-TR')}
                </span>
                <SmallButton onClick={() => startEditing(note)}>Düzenle</SmallButton>
                {confirmingDelete === note.id ? (
                  <>
                    {/* Silme KALICIDIR; tek tıkla olmaz. */}
                    <SmallButton danger onClick={() => void remove(note.id)}>
                      Kalıcı olarak sil
                    </SmallButton>
                    <SmallButton onClick={() => setConfirmingDelete(null)}>Vazgeç</SmallButton>
                  </>
                ) : (
                  <SmallButton onClick={() => setConfirmingDelete(note.id)}>Sil</SmallButton>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};

const Muted = ({ children }: { children: React.ReactNode }) => (
  <div style={{ fontSize: 12.5, color: '#8b96c8', lineHeight: 1.6 }}>{children}</div>
);

const SmallButton = ({
  children,
  onClick,
  danger = false,
}: {
  children: React.ReactNode;
  onClick: () => void;
  danger?: boolean;
}) => (
  <button
    onClick={onClick}
    style={{
      padding: '4px 10px', borderRadius: 8, cursor: 'pointer',
      background: 'transparent',
      border: `1px solid ${danger ? 'rgba(241,121,143,0.35)' : 'rgba(140,150,255,0.18)'}`,
      color: danger ? '#f1798f' : '#c3cbf6',
      fontSize: 11, fontFamily: 'inherit',
    }}
  >
    {children}
  </button>
);
