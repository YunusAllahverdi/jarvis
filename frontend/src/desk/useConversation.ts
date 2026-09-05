import { useCallback, useRef, useState } from 'react';
import { apiClient } from '../api/client';
import type { OrbPhase } from './orb/DeskOrb';

/**
 * Sohbetin durumu ve kürenin fazı.
 *
 * İkisi aynı kancada çünkü küre bir SÜS DEĞİL, isteğin durum
 * göstergesidir. Ayrı yönetilseydi, faz zamanlayıcıyla sürülürdü ve
 * "düşünüyor" görüntüsü isteğin gerçekten sürüp sürmediğinden bağımsız
 * hâle gelirdi — cevap gecikince küre çoktan durmuş olurdu.
 *
 * Oturum kimliği ilk cevapla sunucudan gelir ve sonraki isteklere
 * eklenir; olmasaydı her mesaj yeni bir konuşma başlatır ve Jarvis bir
 * önceki cümleyi hatırlamazdı.
 */

export interface ChatEntry {
  id: string;
  role: 'user' | 'assistant';
  text: string;
  /** Hata mesajları da baloncuk olarak görünür ama farklı boyanır. */
  failed?: boolean;
}

export interface Conversation {
  entries: ChatEntry[];
  phase: OrbPhase;
  busy: boolean;
  sessionId: string | null;
  send: (text: string) => Promise<string | null>;
  setPhase: (phase: OrbPhase) => void;
  clear: () => void;
}

let counter = 0;
const nextId = () => `${Date.now()}-${(counter += 1)}`;

export function useConversation(): Conversation {
  const [entries, setEntries] = useState<ChatEntry[]>([]);
  const [phase, setPhase] = useState<OrbPhase>('idle');
  const [busy, setBusy] = useState(false);
  const sessionRef = useRef<string | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const respondingTimer = useRef<number | undefined>(undefined);

  const send = useCallback(async (text: string): Promise<string | null> => {
    const message = text.trim();
    if (!message || busy) return null;

    setEntries((current) => [
      ...current,
      { id: nextId(), role: 'user', text: message },
    ]);
    setBusy(true);
    setPhase('thinking');

    try {
      const response = await apiClient.chat(message, sessionRef.current);
      sessionRef.current = response.session_id;
      setSessionId(response.session_id);
      setEntries((current) => [
        ...current,
        { id: nextId(), role: 'assistant', text: response.response },
      ]);

      // "Yanıtlıyor" fazı, cevap ekrana geldikten sonra kısa bir süre
      // sürer: küre anında boşta hâline dönseydi, cevabın geldiği anı
      // gösteren tek işaret kaybolurdu.
      setPhase('responding');
      window.clearTimeout(respondingTimer.current);
      respondingTimer.current = window.setTimeout(() => setPhase('idle'), 3200);
      return response.response;
    } catch (cause: unknown) {
      const detail = cause instanceof Error ? cause.message : 'Bir şeyler ters gitti.';
      setEntries((current) => [
        ...current,
        { id: nextId(), role: 'assistant', text: detail, failed: true },
      ]);
      setPhase('idle');
      return null;
    } finally {
      setBusy(false);
    }
  }, [busy]);

  const clear = useCallback(() => {
    setEntries([]);
    sessionRef.current = null;
    setSessionId(null);
    setPhase('idle');
  }, []);

  return { entries, phase, busy, sessionId, send, setPhase, clear };
}
