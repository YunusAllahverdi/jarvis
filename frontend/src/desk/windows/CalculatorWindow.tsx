import { useState } from 'react';
import { C } from '../theme';
import { WindowFrame } from '../WindowFrame';
import type { WindowView } from '../useWindows';

/**
 * Hesap makinesi — tamamen istemcide.
 *
 * Backend'e bağlanmaması bir eksiklik değil: dört işlem için ağ turu
 * atmak, çalışmayan bir sunucuda çalışmayan bir hesap makinesi demek
 * olurdu. Masadaki tek gerçekten yerel araç budur.
 *
 * Ondalık ayırıcı virgüldür (tasarımdaki gibi) ve hesaba girerken
 * noktaya çevrilir.
 */

type Op = '÷' | '×' | '−' | '+';

const ROWS: string[][] = [
  ['AC', '+/-', '%', '÷'],
  ['7', '8', '9', '×'],
  ['4', '5', '6', '−'],
  ['1', '2', '3', '+'],
  ['0', ',', '='],
];

const OPS: string[] = ['÷', '×', '−', '+', '='];
const TOP: string[] = ['AC', '+/-', '%'];

interface Props {
  win: WindowView;
}

export const CalculatorWindow = ({ win }: Props) => {
  const [display, setDisplay] = useState('0');
  const [accumulator, setAccumulator] = useState<number | null>(null);
  const [operator, setOperator] = useState<Op | null>(null);
  // Bir sonraki rakam yeni bir sayı mı başlatıyor? Bayrak olmasaydı
  // "5 + 3" yazarken 3, 5'in yanına eklenip 53 olurdu.
  const [fresh, setFresh] = useState(true);

  const value = (text: string) => Number.parseFloat(text.replace(',', '.'));

  const press = (key: string) => {
    if (key === 'AC') {
      setDisplay('0'); setAccumulator(null); setOperator(null); setFresh(true);
      return;
    }
    if (key === '+/-') {
      setDisplay((current) => (current.startsWith('-') ? current.slice(1) : `-${current}`));
      return;
    }
    if (key === '%') {
      setDisplay(String(value(display) / 100));
      setFresh(true);
      return;
    }
    if (key === '÷' || key === '×' || key === '−' || key === '+') {
      setAccumulator(value(display));
      setOperator(key);
      setFresh(true);
      return;
    }
    if (key === '=') {
      if (operator === null || accumulator === null) return;
      const right = value(display);
      const result =
        operator === '÷'
          // Sıfıra bölme Infinity yerine 0 verir: ekranda "Infinity"
          // görmek, hesap makinesinin bozulduğu izlenimi bırakırdı.
          ? (right === 0 ? 0 : accumulator / right)
          : operator === '×'
            ? accumulator * right
            : operator === '−'
              ? accumulator - right
              : accumulator + right;
      setDisplay(String(Math.round(result * 1e8) / 1e8));
      setAccumulator(null);
      setOperator(null);
      setFresh(true);
      return;
    }
    if (key === ',') {
      setDisplay((current) => (current.includes(',') ? current : `${current},`));
      setFresh(false);
      return;
    }
    setDisplay((current) => (fresh || current === '0' ? key : current + key));
    setFresh(false);
  };

  return (
    <WindowFrame win={win} title="Hesap Makinesi" background="rgba(16,19,27,.92)">
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
        <div
          style={{
            flex: 'none', padding: '10px 20px 14px', textAlign: 'right',
            fontSize: 44, fontWeight: 200, letterSpacing: '-.02em', color: '#f1f4fa',
            overflow: 'hidden', whiteSpace: 'nowrap',
          }}
        >
          {display}
        </div>
        <div
          style={{
            flex: 1, padding: '0 12px 14px', display: 'grid',
            gridTemplateColumns: 'repeat(4,1fr)', gridAutoRows: '1fr', gap: 8,
          }}
        >
          {ROWS.flat().map((key) => (
            <button
              key={key}
              onClick={() => press(key)}
              style={{
                borderRadius: 9, border: 'none', cursor: 'pointer', fontSize: 16,
                fontFamily: 'inherit', color: C.textBright,
                gridColumn: key === '0' ? 'span 2' : 'auto',
                background:
                  key === '='
                    ? C.accent
                    : OPS.includes(key)
                      ? 'rgba(255,255,255,.13)'
                      : TOP.includes(key)
                        ? 'rgba(255,255,255,.10)'
                        : 'rgba(255,255,255,.065)',
              }}
            >
              {key}
            </button>
          ))}
        </div>
      </div>
    </WindowFrame>
  );
};
