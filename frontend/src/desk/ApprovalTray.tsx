import { useCallback, useEffect, useState } from 'react';
import { apiClient, type ApprovalView } from '../api/client';
import { C, MONO } from './theme';

/**
 * Ajanın onay bekleyen araç çağrıları.
 *
 * BU YÜZEY OLMADAN ONAY MODELİ ÇALIŞMAZ ve bunu yaşayarak gördük: ajan
 * bir not yazmak istediğinde çağrı onaya düşüyor, onaylayacak bir yer
 * olmadığı için hiç çalışmıyor ve model "böyle bir aracım yok" diyordu.
 * Kullanıcıya yeteneğin kapalı olduğu gibi görünüyordu; oysa yalnızca
 * kapı çalınıyor ve kimse açmıyordu.
 *
 * Argümanlar TAM olarak gösterilir. "note_write çalıştırılsın mı?" diye
 * sormak, neyin yazılacağını göstermeden onay istemek olurdu — onayın
 * kendisi anlamsızlaşırdı.
 *
 * Kabuğun her yerinde görünür: onay bir kipe ait değildir, ajan hangi
 * ekranda olursanız olun bir şey isteyebilir.
 */

const POLL_MS = 3000;

interface Props {
  sessionId: string | null;
  /** Onaylanan çağrı veri değiştirmiş olabilir; pencereler tazelensin. */
  onResolved: () => void;
}

export const ApprovalTray = ({ sessionId, onResolved }: Props) => {
  const [pending, setPending] = useState<ApprovalView[]>([]);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    void apiClient
      .getApprovals(sessionId)
      .then((result) => setPending(result.pending))
      // Onay servisi kurulu değilse (503) tepsi hiç görünmez. Hata
      // göstermek, kapalı bir yeteneği bozukmuş gibi sunmak olurdu.
      .catch(() => setPending([]));
  }, [sessionId]);

  useEffect(() => {
    load();
    const id = window.setInterval(load, POLL_MS);
    return () => window.clearInterval(id);
  }, [load]);

  const decide = async (approval: ApprovalView, decision: 'approve' | 'reject') => {
    setBusyId(approval.approval_id);
    setError(null);
    try {
      const outcome = await apiClient.decideApproval(approval.approval_id, decision);
      if (outcome.status === 'approved' && outcome.success === false) {
        // Onaylandı ama araç hata verdi. Bunu sessizce yutmak, kullanıcının
        // isteğinin yapıldığını sanmasına yol açardı.
        setError(outcome.error_message ?? 'Araç çalıştı ama başarısız oldu.');
      }
      onResolved();
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : 'Karar iletilemedi.');
    } finally {
      setBusyId(null);
      load();
    }
  };

  if (pending.length === 0 && !error) return null;

  return (
    <div
      style={{
        position: 'absolute', right: 24, top: 120, zIndex: 110, width: 340,
        display: 'flex', flexDirection: 'column', gap: 10,
      }}
    >
      {error ? (
        <div
          style={{
            padding: '10px 14px', borderRadius: 12,
            border: '1px solid rgba(241,121,143,.28)', background: 'rgba(30,16,22,.90)',
            backdropFilter: 'blur(22px)', fontSize: 11.5, lineHeight: 1.55, color: '#f1798f',
          }}
        >
          {error}
        </div>
      ) : null}

      {pending.map((approval) => (
        <div
          key={approval.approval_id}
          style={{
            padding: 14, borderRadius: 14, border: '1px solid rgba(255,255,255,.12)',
            background: 'rgba(18,22,30,.92)', backdropFilter: 'blur(24px)',
            boxShadow: '0 24px 60px rgba(0,0,0,.5)',
            animation: 'deskFadeUp .2s ease both',
          }}
        >
          <div style={{ fontSize: 9.5, letterSpacing: '.26em', color: C.faint }}>ONAY GEREKİYOR</div>
          <div style={{ marginTop: 8, fontSize: 13.5, color: C.textBright }}>
            {approval.tool_name}
            <span style={{ marginLeft: 8, fontSize: 10.5, color: C.faint }}>
              {approval.permission}
            </span>
          </div>

          {approval.reason ? (
            <div style={{ marginTop: 6, fontSize: 11.5, lineHeight: 1.55, color: C.dim }}>
              {approval.reason}
            </div>
          ) : null}

          <pre
            style={{
              marginTop: 10, marginBottom: 0, padding: 10, borderRadius: 9,
              maxHeight: 150, overflow: 'auto',
              background: 'rgba(0,0,0,.34)', border: `1px solid ${C.lineSoft}`,
              fontFamily: MONO, fontSize: 10.5, lineHeight: 1.5,
              color: 'rgba(232,236,244,.76)', whiteSpace: 'pre-wrap', wordBreak: 'break-word',
            }}
          >
            {JSON.stringify(approval.arguments, null, 2)}
          </pre>

          <div style={{ marginTop: 12, display: 'flex', gap: 8 }}>
            <button
              onClick={() => void decide(approval, 'approve')}
              disabled={busyId === approval.approval_id}
              style={{
                flex: 1, height: 34, borderRadius: 9, cursor: 'pointer', fontFamily: 'inherit',
                border: '1px solid rgba(120,200,160,.40)', background: 'rgba(95,211,154,.18)',
                color: '#8fd9b6', fontSize: 12.5,
              }}
            >
              {busyId === approval.approval_id ? '...' : 'Onayla'}
            </button>
            <button
              onClick={() => void decide(approval, 'reject')}
              disabled={busyId === approval.approval_id}
              style={{
                height: 34, padding: '0 14px', borderRadius: 9, cursor: 'pointer',
                fontFamily: 'inherit', border: '1px solid rgba(241,121,143,.32)',
                background: 'transparent', color: '#f1798f', fontSize: 12.5,
              }}
            >
              Reddet
            </button>
          </div>
        </div>
      ))}
    </div>
  );
};
