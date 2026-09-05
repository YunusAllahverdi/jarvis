import { C, MONO } from '../theme';
import type { WindowView } from '../useWindows';

/**
 * Masadaki not kartı.
 *
 * Tek gerçekten dekoratif yüzey budur ve öyle kalması bilinçli: masadaki
 * diğer her pencere bir veriyi gösterir, bu ise yalnızca bir hatırlatma.
 * Standart pencere kabuğunu kullanmaz — trafik ışıkları, içinde
 * yönetilecek bir şey olmayan bir kartta gürültü olurdu.
 */

interface Props {
  win: WindowView;
}

export const QuoteCard = ({ win }: Props) => {
  if (!win.visible) return null;

  return (
    <div
      style={{
        position: 'absolute',
        ...win.style,
        borderRadius: 14,
        border: '1px solid rgba(255,255,255,.08)',
        background: 'rgba(255,255,255,.028)',
        backdropFilter: 'blur(18px)',
        overflow: 'hidden',
      }}
    >
      <div
        onPointerDown={win.onPointerDown}
        style={{
          height: 30, display: 'flex', alignItems: 'center', justifyContent: 'flex-end',
          padding: '0 12px', cursor: 'grab',
        }}
      >
        <button
          onClick={win.onClose}
          aria-label="Kapat"
          style={{ background: 'transparent', border: 'none', color: C.faint, fontSize: 13, cursor: 'pointer', padding: 0 }}
        >
          ×
        </button>
      </div>
      <div style={{ padding: '56px 22px', fontFamily: MONO, fontSize: 13, lineHeight: 1.85, color: 'rgba(232,236,244,.62)' }}>
        Better tools.<br />A calmer mind.<br />A greater you.<br />
        <span style={{ color: C.faint }}>&gt;</span>
      </div>
    </div>
  );
};
