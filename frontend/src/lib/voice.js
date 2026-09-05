// Voice input via Web Speech API (Safari/Chrome, tr-TR). Falls back gracefully when unsupported.
import { useCallback, useEffect, useRef, useState } from "react";

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
  }, [SR, lang, listening, onFinal, onInterim]);

  useEffect(() => () => recRef.current?.abort?.(), []);

  return { supported: !!SR, listening, interim, start, stop, toggle: () => (listening ? stop() : start()) };
}
