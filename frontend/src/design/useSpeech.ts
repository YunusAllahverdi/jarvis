import { useCallback, useEffect, useRef, useState } from 'react';

/**
 * Sesli cevap (TTS) — tarayıcının kendi konuşma motoru.
 *
 * Ek altyapı, ek maliyet ve ek anahtar YOKTUR: Web Speech API her modern
 * tarayıcıda var ve Türkçe destekliyor. Bu, sesin kolay yarısıdır; sesli
 * KOMUT (STT) ayrı bir iştir ve tarayıcıda sürekli dinleyen bir uyandırma
 * kelimesi pratik değildir.
 *
 * Üç davranış bilinçlidir:
 *
 * 1. VARSAYILAN KAPALI. Kullanıcının haberi olmadan konuşan bir sayfa
 *    saygısızlıktır — özellikle sessiz olması gereken bir ortamda açılmışsa.
 * 2. TERCİH HATIRLANIR. localStorage'da tutulur; her açılışta yeniden
 *    açtırmak, özelliği kullanılmaz hâle getirirdi. Okuma/yazma try/catch
 *    içindedir: gizli sekmede ve site verisi engellendiğinde erişimin
 *    kendisi istisna fırlatır.
 * 3. YENİ CEVAP ÖNCEKİNİ KESER. Sıraya almak, kullanıcı üç soru sorduğunda
 *    Jarvis'in eski cevapları arka arkaya okumasına yol açardı.
 */

const STORAGE_KEY = 'jarvis.voice.enabled';

/** Türkçe sesi seçmek için tercih sırası; yoksa tarayıcının varsayılanı. */
const PREFERRED_LANG = 'tr-TR';

function readStoredPreference(): boolean {
  try {
    return window.localStorage.getItem(STORAGE_KEY) === 'true';
  } catch {
    // Gizli sekme veya site verisi engellenmiş: tercih okunamaz, kapalı kal.
    return false;
  }
}

function writeStoredPreference(enabled: boolean): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, String(enabled));
  } catch {
    // Yazılamaması bir hata değildir; yalnızca tercih kalıcı olmaz.
  }
}

export interface Speech {
  /** Tarayıcı konuşma motorunu destekliyor mu? */
  supported: boolean;
  enabled: boolean;
  speaking: boolean;
  /** Sesi açar/kapatır ve YENİ durumu döndürür. */
  toggle: () => boolean;
  /** Metni seslendirir; kapalıysa veya desteklenmiyorsa hiçbir şey yapmaz. */
  speak: (text: string) => void;
  /** Konuşmayı hemen keser. */
  stop: () => void;
}

export const useSpeech = (): Speech => {
  const supported =
    typeof window !== 'undefined' && typeof window.speechSynthesis !== 'undefined';

  const [enabled, setEnabled] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const voiceRef = useRef<SpeechSynthesisVoice | null>(null);

  /* Açık/kapalı durumu AYRICA bir ref'te tutulur ve state ile birlikte
   * güncellenir. Sebebi somut bir hatadır: `speak` yalnızca state'i okusaydı,
   * sesi açan tıklamanın hemen ardından yapılan konuşma çağrısı hâlâ eski
   * (kapalı) değeri görür ve sessizce hiçbir şey yapmazdı — kullanıcı da
   * sesi açtığını duyamazdı. Ref, aynı olay içinde güncel değeri verir. */
  const enabledRef = useRef(false);

  const applyEnabled = useCallback((next: boolean) => {
    enabledRef.current = next;
    setEnabled(next);
  }, []);

  // Tercih ilk render'dan SONRA okunur: localStorage'a render sırasında
  // dokunmak, sunucuda çalışan bir render'da patlardı.
  useEffect(() => {
    if (supported) applyEnabled(readStoredPreference());
  }, [supported, applyEnabled]);

  /* Ses listesi tarayıcıda ASENKRON dolar: ilk çağrıda çoğu tarayıcı boş
   * dizi döndürür ve `voiceschanged` olayından sonra dolar. Yalnızca ilk
   * çağrıya bakılsaydı Türkçe ses çoğu zaman bulunamazdı. */
  useEffect(() => {
    if (!supported) return;

    const pickVoice = () => {
      const voices = window.speechSynthesis.getVoices();
      voiceRef.current =
        voices.find((voice) => voice.lang === PREFERRED_LANG) ??
        voices.find((voice) => voice.lang.startsWith('tr')) ??
        null;
    };

    pickVoice();
    window.speechSynthesis.addEventListener('voiceschanged', pickVoice);
    return () => {
      window.speechSynthesis.removeEventListener('voiceschanged', pickVoice);
      window.speechSynthesis.cancel();
    };
  }, [supported]);

  const stop = useCallback(() => {
    if (!supported) return;
    window.speechSynthesis.cancel();
    setSpeaking(false);
  }, [supported]);

  const speak = useCallback(
    (text: string) => {
      const trimmed = text.trim();
      // State değil REF okunur; gerekçe yukarıda.
      if (!supported || !enabledRef.current || !trimmed) return;

      // Yeni cevap öncekini keser; sıraya alınsaydı Jarvis eski cevapları
      // arka arkaya okurdu.
      window.speechSynthesis.cancel();

      const utterance = new SpeechSynthesisUtterance(trimmed);
      utterance.lang = PREFERRED_LANG;
      if (voiceRef.current) utterance.voice = voiceRef.current;
      utterance.onend = () => setSpeaking(false);
      utterance.onerror = () => setSpeaking(false);

      setSpeaking(true);
      window.speechSynthesis.speak(utterance);
    },
    [supported],
  );

  /**
   * Sesi açar/kapatır ve YENİ durumu döndürür.
   *
   * Dönüş değeri bir kolaylık değil, gerekliliktir: çağıran, açılışta bir
   * onay cümlesi okutmak isteyebilir ve React state'i o anda henüz
   * güncellenmemiş olur. Yeni değer buradan dönmezse çağıranın elinde
   * güvenilir bir "artık açık mı?" cevabı olmaz.
   */
  const toggle = useCallback((): boolean => {
    const next = !enabledRef.current;
    applyEnabled(next);
    writeStoredPreference(next);
    // Kapatmak susturmayı da kapsamalı: aksi hâlde kullanıcı sesi
    // kapattığında o an okunan cevap sonuna kadar devam ederdi.
    if (!next && supported) {
      window.speechSynthesis.cancel();
      setSpeaking(false);
    }
    return next;
  }, [supported, applyEnabled]);

  return { supported, enabled, speaking, toggle, speak, stop };
};
