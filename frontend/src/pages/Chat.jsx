// Chat page — streaming conversation with SSE, curtain-rise entrance, session sidebar.
import React, { useEffect, useRef, useState } from "react";
import { ArrowUp, RotateCcw, Trash2, Plus, MessageSquare, Mic } from "lucide-react";
import { toast } from "sonner";
import { api, streamChat } from "@/lib/api";
import { useOrb } from "@/state/orb";
import { useVoice } from "@/lib/voice";

function useAutoScroll(dep) {
  const ref = useRef(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  }, [dep]);
  return ref;
}

export default function Chat() {
  const { setOrb } = useOrb();

  const [sessionId, setSessionId] = useState(null);
  const [messages, setMessages] = useState([]); // {role, content, streaming?}
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [sessions, setSessions] = useState([]);
  const abortRef = useRef(null);

  const scrollRef = useAutoScroll(messages);
  const voice = useVoice({ onFinal: (t) => send(t), onInterim: (t) => setInput(t) });
  const talk = () => {
    if (!voice.supported) { toast("Bu tarayıcı sesli girişi desteklemiyor."); return; }
    voice.toggle();
  };
  useEffect(() => {
    if (voice.listening) setOrb("listening", { label: "Dinliyor" });
    else if (!busy) setOrb("idle", { label: "Hazır" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [voice.listening]);
  useEffect(() => {
    const h = () => talk();
    window.addEventListener("jarvis:talk", h);
    return () => window.removeEventListener("jarvis:talk", h);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [voice.listening, voice.supported]);

  const refreshSessions = () =>
    api.listSessions().then((r) => setSessions(r.sessions || [])).catch(() => {});

  useEffect(() => {
    refreshSessions();
    const pending = sessionStorage.getItem("jarvis.pendingPrompt");
    if (pending) {
      sessionStorage.removeItem("jarvis.pendingPrompt");
      setTimeout(() => send(pending), 260); // let curtain animation begin
    }
    if (sessionStorage.getItem("jarvis.autoTalk")) {
      sessionStorage.removeItem("jarvis.autoTalk");
      setTimeout(() => window.dispatchEvent(new Event("jarvis:talk")), 700);
    }
    return () => abortRef.current?.abort?.();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const send = async (text) => {
    const msg = (text ?? input).trim();
    if (!msg || busy) return;
    setInput("");
    setBusy(true);
    setOrb("thinking", { label: "Düşünüyor" });

    const nextMessages = [...messages, { role: "user", content: msg }];
    setMessages([...nextMessages, { role: "assistant", content: "", streaming: true }]);

    const ac = new AbortController();
    abortRef.current = ac;

    let acc = "";
    await streamChat({
      message: msg,
      session_id: sessionId,
      signal: ac.signal,
      onSession: (sid) => setSessionId(sid),
      onDelta: (d) => {
        acc += d;
        setOrb("streaming", { label: "Aktarıyor" });
        setMessages((prev) => {
          const copy = prev.slice();
          const last = copy[copy.length - 1];
          if (last?.streaming) copy[copy.length - 1] = { ...last, content: acc };
          return copy;
        });
      },
      onDone: () => {
        setMessages((prev) => {
          const copy = prev.slice();
          const last = copy[copy.length - 1];
          if (last?.streaming) copy[copy.length - 1] = { role: "assistant", content: acc || last.content };
          return copy;
        });
        setBusy(false);
        setOrb("idle", { label: "Hazır" });
        refreshSessions();
      },
      onError: (err) => {
        setMessages((prev) => {
          const copy = prev.slice();
          const last = copy[copy.length - 1];
          // Sebebi GÖSTER: axios'un "Request failed with status code 502"
          // mesajı kullanıcıya hiçbir şey söylemiyordu. Backend hatanın
          // ne olduğunu zaten yazıyor (ör. "Sağlayıcı hatası (401): API key
          // is invalid.") ve düzeltilebilir tek bilgi orada.
          const errText = `⚠ ${err?.jarvis?.message || err?.message || "Bağlantı hatası"}`;
          if (last?.streaming) copy[copy.length - 1] = { role: "assistant", content: errText, error: true };
          return copy;
        });
        setBusy(false);
        setOrb("error", { label: "Hata" });
      },
    });
  };

  const loadSession = async (sid) => {
    setSessionId(sid);
    const r = await api.sessionMessages(sid);
    setMessages((r.messages || []).map((m) => ({ role: m.role, content: m.content })));
  };

  const newChat = () => {
    setSessionId(null);
    setMessages([]);
    setOrb("idle", { label: "Hazır" });
  };

  const removeSession = async (sid) => {
    await api.deleteSession(sid);
    if (sid === sessionId) newChat();
    refreshSessions();
  };

  return (
    <main
      className="h-full w-full pt-14 flex"
      data-testid="chat-page"
    >
      {/* Sessions sidebar */}
      <aside className="hidden md:flex w-64 flex-col border-r hairline p-3 gap-2 overflow-hidden">
        <div className="flex items-center justify-between">
          <span className="text-[10px] tracking-[0.28em] uppercase text-muted font-mono">Oturumlar</span>
          <button
            onClick={newChat}
            className="pill flex items-center gap-1 hover:text-white"
            data-testid="chat-new"
          >
            <Plus size={12} /> yeni
          </button>
        </div>
        <div className="flex-1 overflow-y-auto -mx-1 px-1">
          {sessions.length === 0 && (
            <p className="text-xs text-muted mt-4">Henüz oturum yok.</p>
          )}
          <ul className="space-y-1">
            {sessions.map((s) => (
              <li key={s.id}>
                <div
                  className={`group flex items-center gap-2 px-2.5 py-2 rounded-md text-xs cursor-pointer hover:bg-white/5 ${
                    s.id === sessionId ? "bg-white/10 border border-white/10" : ""
                  }`}
                  data-testid={`chat-session-${s.id}`}
                  onClick={() => loadSession(s.id)}
                >
                  <MessageSquare size={12} className="text-muted shrink-0" />
                  <span className="truncate flex-1">{s.last_snippet || "(boş)"}</span>
                  <button
                    onClick={(e) => { e.stopPropagation(); removeSession(s.id); }}
                    className="opacity-0 group-hover:opacity-100 text-muted hover:text-red-400"
                    aria-label="Sil"
                  >
                    <Trash2 size={12} />
                  </button>
                </div>
              </li>
            ))}
          </ul>
        </div>
      </aside>

      {/* Conversation */}
      <section className="flex-1 flex flex-col min-w-0">
        <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 md:px-10 py-8">
          <div className="mx-auto max-w-3xl space-y-6">
            {messages.length === 0 && (
              <div className="text-center pt-24 text-muted">
                <p className="font-display text-2xl text-white">Sohbet başlığa hazır</p>
                <p className="text-sm mt-2">Aşağıdaki kutuya yazın — Jarvis akış hâlinde yanıtlar.</p>
              </div>
            )}
            {messages.map((m, i) => (
              <MessageRow key={i} m={m} />
            ))}
          </div>
        </div>

        <div className="border-t hairline px-4 md:px-10 py-4">
          <div className="mx-auto max-w-3xl">
            <div className="glass rounded-[22px] p-2 flex items-end gap-2">
              <textarea
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
                }}
                rows={1}
                placeholder="Jarvis'e yazın…"
                disabled={busy}
                className="flex-1 resize-none bg-transparent outline-none px-4 py-3 text-[15px] placeholder:text-[#8a93a8] disabled:opacity-60"
                data-testid="chat-input"
              />
              {busy ? (
                <button
                  onClick={() => abortRef.current?.abort()}
                  className="pill hover:text-white"
                  data-testid="chat-stop"
                >
                  durdur
                </button>
              ) : null}
              <button
                onClick={talk}
                className={`rounded-full h-10 w-10 flex items-center justify-center transition ${voice.listening ? "bg-[#ff3b30] text-white animate-pulse" : "text-secondary hover:text-white hover:bg-white/10"}`}
                aria-label="Sesle yaz"
                data-testid="chat-mic"
              >
                <Mic size={17} />
              </button>
              <button
                onClick={() => send()}
                disabled={!input.trim() || busy}
                className="electric-btn rounded-full h-10 w-10 flex items-center justify-center disabled:opacity-40"
                aria-label="Gönder"
                data-testid="chat-send"
              >
                <ArrowUp size={18} />
              </button>
            </div>
            <div className="flex items-center justify-between mt-2 text-[11px] text-muted">
              <span>Oturum: <span className="font-mono">{sessionId?.slice(0, 8) || "yeni"}</span></span>
              <button
                onClick={newChat}
                className="hover:text-white flex items-center gap-1"
                data-testid="chat-reset"
              >
                <RotateCcw size={11} /> yeni sohbet
              </button>
            </div>
          </div>
        </div>
      </section>
    </main>
  );
}

function MessageRow({ m }) {
  const isUser = m.role === "user";
  return (
    <div className={`msg-enter flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[85%] rounded-[20px] px-4 py-3 text-[15px] leading-relaxed whitespace-pre-wrap ${
          isUser ? "bubble-user" : m.error ? "bubble-error" : "glass"
        }`}
        data-testid={isUser ? "user-message" : "assistant-message"}
      >
        {!isUser && <div className="text-[10px] tracking-[0.28em] uppercase text-muted font-mono mb-1">J.A.R.V.I.S</div>}
        {m.content || (m.streaming ? <span className="text-muted animate-pulse">yanıt akıyor…</span> : null)}
      </div>
    </div>
  );
}
