// Home — 3D glass orb (tap to talk) + Turkish prompt. Enter → Chat with Apple-like transition.
import React, { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import Orb from "@/components/Orb";
import { useOrb } from "@/state/orb";
import { useVoice } from "@/lib/voice";
import { ArrowUp, Mic } from "lucide-react";

const HINTS = [
  "Bugün için üç önemli görev çıkar",
  "Yarınki toplantı için not al: gündem taslağı",
  "Council'e sor: bu fikrin en zayıf tarafı ne?",
  "Kod tabanımdaki en son değişiklikleri özetle",
];

export default function Home() {
  const [value, setValue] = useState("");
  const [hint, setHint] = useState(0);
  const nav = useNavigate();
  const { setOrb } = useOrb();
  const inputRef = useRef(null);

  const go = (text) => {
    const v = (text ?? value).trim();
    if (!v) return;
    sessionStorage.setItem("jarvis.pendingPrompt", v);
    setOrb("thinking", { label: "Bağlantı kuruluyor" });
    nav("/chat", { state: { fromHome: true } });
  };

  const voice = useVoice({ onFinal: (t) => go(t) });

  useEffect(() => {
    setOrb(voice.listening ? "listening" : "idle", { label: voice.listening ? "Dinliyor" : "Hazır" });
  }, [voice.listening, setOrb]);

  useEffect(() => {
    inputRef.current?.focus();
    const t = setInterval(() => setHint((h) => (h + 1) % HINTS.length), 3800);
    return () => clearInterval(t);
  }, []);

  const talk = () => {
    if (!voice.supported) { toast("Bu tarayıcı sesli girişi desteklemiyor — yazarak devam edin."); inputRef.current?.focus(); return; }
    voice.toggle();
  };

  return (
    <main className="relative h-full w-full flex flex-col items-center justify-center pt-14 px-6" data-testid="home-page">
      <div className="absolute top-24 left-1/2 -translate-x-1/2 text-center">
        <p className="text-[10px] tracking-[0.4em] uppercase text-muted font-mono">Kişisel AI Çalışma Katmanı</p>
        <h1 className="mt-3 font-display text-4xl sm:text-5xl lg:text-6xl font-medium tracking-tight">
          <span className="text-white">Merhaba, ben </span>
          <span className="electric-text">Jarvis</span>
          <span className="text-white">.</span>
        </h1>
      </div>

      <div className="flex-1 flex flex-col items-center justify-center w-full">
        <Orb
          size={Math.min(420, window.innerWidth * 0.7)}
          state={voice.listening ? "listening" : "idle"}
          testId="home-orb"
          interactive
          onClick={talk}
        />
        <p className="h-6 text-sm text-secondary -mt-4 text-center transition-opacity" data-testid="home-voice-status">
          {voice.listening ? (voice.interim || "Dinliyorum… konuşabilirsiniz") : <span className="text-muted">Konuşmak için küreye dokun</span>}
        </p>
      </div>

      <div className="w-full max-w-2xl pb-24 z-10">
        <div className="glass rounded-[22px] p-2 flex items-end gap-2">
          <textarea
            ref={inputRef}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); go(); } }}
            rows={1}
            placeholder="Komut veya soru yazın… (Enter ile gönder, Shift+Enter yeni satır)"
            className="flex-1 resize-none bg-transparent outline-none px-4 py-3 text-[15px] placeholder:text-[#8a93a8]"
            data-testid="home-input"
          />
          <button
            onClick={talk}
            className={`rounded-full h-10 w-10 flex items-center justify-center transition ${voice.listening ? "bg-[#ff3b30] text-white animate-pulse" : "text-secondary hover:text-white hover:bg-white/10"}`}
            aria-label="Sesle yaz"
            data-testid="home-mic"
          >
            <Mic size={17} />
          </button>
          <button
            onClick={() => go()}
            disabled={!value.trim()}
            className="electric-btn rounded-full h-10 w-10 flex items-center justify-center disabled:opacity-40 disabled:cursor-not-allowed"
            aria-label="Gönder"
            data-testid="home-submit"
          >
            <ArrowUp size={18} />
          </button>
        </div>
        <div className="mt-3 flex items-center gap-2 justify-center text-xs text-muted">
          <span className="pill font-mono">⌘K</span>
          <span>komut paleti</span>
          <span className="mx-2 opacity-30">·</span>
          <span className="italic opacity-70" data-testid="home-hint">"{HINTS[hint]}"</span>
        </div>
      </div>
    </main>
  );
}
