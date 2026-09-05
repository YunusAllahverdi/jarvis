// Voice input via Web Speech API (Safari/Chrome, tr-TR). Falls back gracefully when unsupported.
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";

const SR = typeof window !== "undefined" ? window.SpeechRecognition || window.webkitSpeechRecognition : null;

export function useVoice({ onFinal, onInterim, lang = "tr-TR" } = {}) {
  const recRef = useRef(null);
  const [listening, setListening] = useState(false);
  const [interim, setInterim] = useState("");

  const stop = useCallback(() => {
    recRef.current?.stop();
    setListening(false);
  }, []);

  const start = useCallback(() => {
    if (!SR || listening) return false;
    const rec = new SR();
    rec.lang = lang;
    rec.interimResults = true;
    rec.continuous = false;
    rec.maxAlternatives = 1;
    let finalText = "";
    rec.onresult = (e) => {
      let live = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const tr = e.results[i][0].transcript;
        if (e.results[i].isFinal) finalText += tr;
        else live += tr;
      }
      setInterim(live || finalText);
      onInterim?.(live || finalText);
    };
    rec.onerror = () => { setListening(false); setInterim(""); };
    rec.onend = () => {
      setListening(false);
      setInterim("");
      const text = finalText.trim();
      if (text) onFinal?.(text);
    };
    recRef.current = rec;
    rec.start();
    setListening(true);
    return true;
  }, [lang, listening, onFinal, onInterim]);

  useEffect(() => () => recRef.current?.abort?.(), []);

  return { supported: !!SR, listening, interim, start, stop, toggle: () => (listening ? stop() : start()) };
}


/**
 * Sesli yanıt (TTS).
 *
 * Önce sunucudaki ElevenLabs denenir; kapalıysa, kotası dolduysa ya da ağ
 * giderse tarayıcının kendi motoruna DÜŞÜLÜR. Sessiz kalmak, sesin
 * sebepsizce kesilmesi ve kullanıcının nedenini hiç öğrenememesi demek
 * olurdu.
 *
 * Sunucu sesinin kapalı olduğu bir kez öğrenilir ve saklanır: her cevapta
 * yeniden yoklamak, kapalı bir yetenek için her seferinde bir 503 turu
 * atmak ve konuşmayı geciktirmek demekti.
 */
export function useSpeak() {
  const [speaking, setSpeaking] = useState(false);
  const audioRef = useRef(null);
  const serverOkRef = useRef(null);

  const stop = useCallback(() => {
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current = null;
    }
    if (typeof window !== "undefined" && window.speechSynthesis) {
      window.speechSynthesis.cancel();
    }
    setSpeaking(false);
  }, []);

  const browserSpeak = useCallback((text) => {
    if (typeof window === "undefined" || !window.speechSynthesis) return;
    const u = new SpeechSynthesisUtterance(text);
    u.lang = "tr-TR";
    u.onend = () => setSpeaking(false);
    u.onerror = () => setSpeaking(false);
    setSpeaking(true);
    window.speechSynthesis.speak(u);
  }, []);

  const speak = useCallback(
    async (text) => {
      const clean = (text || "").trim();
      if (!clean) return;

      // Yeni cevap öncekini keser — İKİ motoru da; yalnızca biri
      // susturulsaydı cevap üst üste iki sesle duyulurdu.
      stop();

      if (serverOkRef.current === false) {
        browserSpeak(clean);
        return;
      }

      try {
        const blob = await api.tts(clean);
        const audio = new Audio(URL.createObjectURL(blob));
        audioRef.current = audio;
        const release = () => {
          URL.revokeObjectURL(audio.src);
          setSpeaking(false);
        };
        audio.onended = release;
        audio.onerror = release;
        setSpeaking(true);
        await audio.play();
        serverOkRef.current = true;
      } catch {
        serverOkRef.current = false;
        browserSpeak(clean);
      }
    },
    [stop, browserSpeak],
  );

  useEffect(() => stop, [stop]);

  return { speak, stop, speaking };
}
