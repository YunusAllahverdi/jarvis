import { useCallback, useEffect, useRef, useState } from 'react';

/**
 * Sesli komut (STT) — BAS-KONUŞ.
 *
 * Sürekli dinleyen bir uyandırma kelimesi bilinçli olarak YAPILMADI ve bu
 * bir eksiklik değil, tarayıcının sınırı:
 *
 * - Sekme önde olmalıdır; arka planda tanıma durur.
 * - İzin her oturumda yenilenir.
 * - Chrome ve Edge sesi Google'ın sunucularına gönderir. Yani "yerel"
 *   değildir ve kullanıcının bunu bilmesi gerekir.
 *
 * Sürekli dinleme, bu üç şartın altında ya çalışmayan ya da sessizce sesi
 * dışarı gönderen bir özellik olurdu. Bas-konuş, kullanıcının ne zaman
 * dinlendiğini bildiği tek biçimdir. Tam eller serbest deneyim tarayıcının
 * değil, bir masaüstü uygulamasının işidir.
 *
 * Tanınan metin OTOMATİK GÖNDERİLMEZ: tanıma hata yapar ve yanlış anlaşılmış
 * bir cümlenin doğrudan ajana gitmesi, kullanıcının yazmadığı bir isteği
 * çalıştırmak olurdu. Metin girişe yazılır, göndermeye kullanıcı karar verir.
 */

/** Tarayıcının `SpeechRecognition` yapıcısı; standart dışı olduğu için türsüz. */
type RecognitionConstructor = new () => SpeechRecognitionLike;

interface SpeechRecognitionLike {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  maxAlternatives: number;
  start: () => void;
  stop: () => void;
  abort: () => void;
  onresult: ((event: SpeechRecognitionEventLike) => void) | null;
  onerror: ((event: { error: string }) => void) | null;
  onend: (() => void) | null;
}

interface SpeechRecognitionEventLike {
  results: ArrayLike<ArrayLike<{ transcript: string }> & { isFinal: boolean }>;
  resultIndex: number;
}

function getRecognitionConstructor(): RecognitionConstructor | null {
  if (typeof window === 'undefined') return null;
  const scope = window as unknown as {
    SpeechRecognition?: RecognitionConstructor;
    webkitSpeechRecognition?: RecognitionConstructor;
  };
  return scope.SpeechRecognition ?? scope.webkitSpeechRecognition ?? null;
}

export interface Dictation {
  /** Tarayıcı konuşma tanımayı destekliyor mu? */
  supported: boolean;
  listening: boolean;
  /** Son hata (izin reddi, ağ vb.); yoksa null. */
  error: string | null;
  start: () => void;
  stop: () => void;
}

export const useDictation = (onTranscript: (text: string) => void): Dictation => {
  const [supported] = useState(() => getRecognitionConstructor() !== null);
  const [listening, setListening] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);
  // Geri çağrı bir ref'te tutulur: her render'da yeniden bağlanmak, konuşma
  // sırasında tanıyıcıyı yeniden kurup dinlemeyi kesebilirdi.
  const callbackRef = useRef(onTranscript);
  useEffect(() => { callbackRef.current = onTranscript; }, [onTranscript]);

  const stop = useCallback(() => {
    const recognition = recognitionRef.current;
    if (recognition) {
      try {
        recognition.stop();
      } catch {
        // Zaten durmuş olabilir; durdurmanın başarısızlığı bir hata değildir.
      }
    }
    setListening(false);
  }, []);

  const start = useCallback(() => {
    const Constructor = getRecognitionConstructor();
    if (!Constructor || listening) return;

    setError(null);
    const recognition = new Constructor();
    recognition.lang = 'tr-TR';
    // Tek bir söyleyiş alınır: sürekli mod, kullanıcı bıraktığını sandıktan
    // sonra da dinlemeye devam ederdi.
    recognition.continuous = false;
    recognition.interimResults = false;
    recognition.maxAlternatives = 1;

    recognition.onresult = (event) => {
      let text = '';
      for (let index = event.resultIndex; index < event.results.length; index += 1) {
        text += event.results[index][0].transcript;
      }
      const trimmed = text.trim();
      // Metin yalnızca AKTARILIR; gönderme kararı kullanıcınındır.
      if (trimmed) callbackRef.current(trimmed);
    };

    recognition.onerror = (event) => {
      setError(
        event.error === 'not-allowed'
          ? 'Mikrofon izni verilmedi.'
          : event.error === 'no-speech'
            ? 'Ses algılanmadı.'
            : 'Konuşma tanınamadı.',
      );
      setListening(false);
    };

    recognition.onend = () => setListening(false);

    recognitionRef.current = recognition;
    try {
      recognition.start();
      setListening(true);
    } catch {
      setError('Dinleme başlatılamadı.');
      setListening(false);
    }
  }, [listening]);

  // Bileşen kaldırıldığında tanıma bırakılmaz: arkada çalışmaya devam eden
  // bir tanıyıcı, mikrofonu açık tutar.
  useEffect(() => () => {
    const recognition = recognitionRef.current;
    if (recognition) {
      try {
        recognition.abort();
      } catch {
        // Yok sayılır.
      }
    }
  }, []);

  return { supported, listening, error, start, stop };
};
