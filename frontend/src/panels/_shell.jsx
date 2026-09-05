// Simple shared panel chrome + helpers
import React, { useState } from "react";
import { Sparkles, ArrowUp } from "lucide-react";
import { api, NOT_CONNECTED } from "@/lib/api";

export function PanelShell({ title, subtitle, right, children, testId, command, onCommandDone }) {
  return (
    <div className="h-full flex flex-col" data-testid={testId}>
      <div className="px-6 py-4 border-b hairline flex items-center justify-between shrink-0">
        <div>
          <h2 className="font-display text-lg text-white">{title}</h2>
          {subtitle && <p className="text-xs text-muted mt-0.5">{subtitle}</p>}
        </div>
        {right}
      </div>
      <div className="flex-1 overflow-y-auto">{children}</div>
      {command && <CommandBar panel={command} onDone={onCommandDone} />}
    </div>
  );
}

const PLACEHOLDERS = {
  notes: "Jarvis'e söyle: \"Yarınki toplantı için gündem notu yaz\"",
  approvals: "Jarvis'e söyle: \"İlk isteği onayla\" / \"Hepsini reddet\"",
  memory: "Jarvis'e söyle: \"Kahvemi sütsüz içtiğimi hatırla\"",
  checkpoints: "Jarvis'e söyle: \"plan.md için geri alma noktası aç\"",
  calendar: "Jarvis'e söyle: \"Cuma 15:00 diş hekimi, 45 dk\"",
  reminders: "Jarvis'e söyle: \"Yarın faturayı öde — yüksek öncelik\"",
};

export function CommandBar({ panel, onDone }) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [reply, setReply] = useState(null);

  const run = async () => {
    const msg = text.trim();
    if (!msg || busy) return;
    setBusy(true);
    setReply(null);
    try {
      const r = await api.panelCommand(panel, msg);
      setReply({ text: r.reply, actions: r.actions || [] });
      setText("");
      onDone?.(r);
    } catch (e) {
      setReply({ text: e?.jarvis?.message || e.message, error: true });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="cmd-bar shrink-0 px-4 pt-3 pb-3" data-testid={`cmd-bar-${panel}`}>
      {reply && (
        <div className={`cmd-reply mb-2 flex items-start gap-2 text-[13px] ${reply.error ? "text-red-300" : "text-secondary"}`} data-testid="cmd-reply">
          <Sparkles size={13} className="electric-text mt-0.5 shrink-0" />
          <div>
            <span>{reply.text}</span>
            {reply.actions?.length > 0 && (
              <span className="ml-2 text-[11px] text-muted">· {reply.actions.join(", ")}</span>
            )}
          </div>
        </div>
      )}
      <div className="flex items-center gap-2 bg-white rounded-full border border-black/10 pl-4 pr-1.5 py-1 shadow-sm">
        <Sparkles size={14} className="electric-text shrink-0" />
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && run()}
          disabled={busy}
          placeholder={PLACEHOLDERS[panel] || "Jarvis'e söyle…"}
          className="flex-1 bg-transparent outline-none text-[14px] py-1.5 placeholder:text-[#a0a6b1] text-[#1d1d1f] disabled:opacity-60"
          data-testid={`cmd-input-${panel}`}
        />
        <button
          onClick={run}
          disabled={!text.trim() || busy}
          className="electric-btn rounded-full h-8 w-8 flex items-center justify-center disabled:opacity-40"
          aria-label="Gönder"
          data-testid={`cmd-send-${panel}`}
        >
          {busy ? <span className="w-3 h-3 rounded-full border-2 border-white/40 border-t-white animate-spin" /> : <ArrowUp size={15} />}
        </button>
      </div>
    </div>
  );
}

export function Empty({ label, hint, testId }) {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-center" data-testid={testId}>
      <div className="w-10 h-10 rounded-full mb-3 border hairline flex items-center justify-center">
        <div className="w-2 h-2 rounded-full" style={{ background: "var(--electric)" }} />
      </div>
      <p className="text-sm text-white">{label}</p>
      {hint && <p className="text-xs text-muted mt-1 max-w-sm">{hint}</p>}
    </div>
  );
}

/**
 * Hata kutusu — üç DURUMU ayırır çünkü kullanıcının yapacağı şey farklıdır.
 *
 *   * "bağlı değil"  : yetenek hiç kurulmamış. Yapılacak bir şey yok,
 *                      kırmızı göstermek yanlış alarm olurdu.
 *   * "anahtar lazım": sunucu ayakta ama kimlik istiyor. Ayarlar'dan
 *                      anahtar girilir.
 *   * gerçek hata    : bir şey bozuldu.
 *
 * Üçü aynı kırmızı kutuda gösterilseydi, kullanıcı kurulmamış bir
 * özelliği bozuk sanır ve olmayan bir arızayı aramaya başlardı.
 */
export function ErrorNote({ err, testId }) {
  const j = err?.jarvis || {};
  const msg = j.message || err?.message || "Bilinmeyen hata";

  if (j.code === NOT_CONNECTED) {
    return (
      <div className="m-6 p-4 rounded-lg border hairline glass-soft" data-testid={testId}>
        <p className="text-[10px] uppercase tracking-[0.28em] font-mono text-muted mb-1">
          Bağlı değil
        </p>
        <p className="text-sm text-white">{msg}</p>
        {j.why && <p className="text-xs text-muted mt-1.5 leading-relaxed">{j.why}</p>}
      </div>
    );
  }

  if (j.needsAuth) {
    return (
      <div
        className="m-6 p-4 rounded-lg border"
        style={{ borderColor: "rgba(245,158,11,0.35)", background: "rgba(245,158,11,0.06)" }}
        data-testid={testId}
      >
        <p className="text-[10px] uppercase tracking-[0.28em] font-mono mb-1" style={{ color: "#fbe1a3" }}>
          Erişim anahtarı gerekiyor
        </p>
        <p className="text-sm" style={{ color: "#fbe1a3" }}>{msg}</p>
        <p className="text-xs text-muted mt-1.5">Ayarlar panelinden anahtarı girin.</p>
      </div>
    );
  }

  return (
    <div
      className="m-6 p-4 rounded-lg border"
      style={{ borderColor: "rgba(239,68,68,0.35)", background: "rgba(239,68,68,0.06)" }}
      data-testid={testId}
    >
      <p className="text-xs uppercase tracking-widest font-mono text-red-300 mb-1">Hata</p>
      <p className="text-sm text-red-200">{msg}</p>
    </div>
  );
}

export function LoadingBlock() {
  return (
    <div className="p-6 space-y-3">
      {[...Array(4)].map((_, i) => (
        <div key={i} className="h-12 rounded-lg glass-soft animate-pulse" />
      ))}
    </div>
  );
}

export function Field({ label, hint, children }) {
  return (
    <label className="block">
      <div className="text-[10px] uppercase tracking-[0.25em] font-mono text-muted mb-1">{label}</div>
      {children}
      {hint && <div className="text-[11px] text-muted mt-1">{hint}</div>}
    </label>
  );
}

export function Input(props) {
  return (
    <input
      {...props}
      className={`w-full bg-black/30 border hairline rounded-md px-3 py-2 text-sm outline-none focus:border-[rgba(47,111,237,0.6)] ${props.className || ""}`}
    />
  );
}

export function TextArea(props) {
  return (
    <textarea
      {...props}
      className={`w-full bg-black/30 border hairline rounded-md px-3 py-2 text-sm outline-none focus:border-[rgba(47,111,237,0.6)] resize-y ${props.className || ""}`}
    />
  );
}

export function Btn({ children, kind = "ghost", ...rest }) {
  const base = "text-xs px-3 py-1.5 rounded-md transition";
  const styles = {
    ghost:     "border hairline text-secondary hover:text-white hover:bg-white/5",
    primary:   "electric-btn",
    danger:    "border border-red-500/40 text-red-300 hover:bg-red-500/10",
    subtle:    "bg-white/5 text-secondary hover:text-white",
  };
  return <button {...rest} className={`${base} ${styles[kind]} ${rest.className || ""}`}>{children}</button>;
}
