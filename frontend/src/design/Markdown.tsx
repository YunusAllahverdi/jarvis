/**
 * Hafif Markdown renderer — harici kütüphane yok.
 * Desteklenenler: **kalın**, *italik*, `kod`, ```blok```, # başlık,
 * - liste, > alıntı, --- yatay çizgi, [link](url)
 */

interface Props {
  text: string;
  style?: React.CSSProperties;
}

function escapeHtml(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function parseInline(raw: string): string {
  let s = escapeHtml(raw);
  // Kod span — önce işle ki içindekiler etkilenmesin
  s = s.replace(/`([^`]+)`/g, '<code>$1</code>');
  // Kalın+italik
  s = s.replace(/\*\*\*(.+?)\*\*\*/g, '<strong><em>$1</em></strong>');
  // Kalın
  s = s.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  // İtalik
  s = s.replace(/\*(.+?)\*/g, '<em>$1</em>');
  s = s.replace(/_(.+?)_/g, '<em>$1</em>');
  // Link
  s = s.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
  return s;
}

function parseBlock(lines: string[]): string {
  const out: string[] = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    // Kod bloğu
    if (line.startsWith('```')) {
      const lang = line.slice(3).trim();
      const codeLines: string[] = [];
      i++;
      while (i < lines.length && !lines[i].startsWith('```')) {
        codeLines.push(escapeHtml(lines[i]));
        i++;
      }
      out.push(`<pre data-lang="${lang}"><code>${codeLines.join('\n')}</code></pre>`);
      i++;
      continue;
    }

    // Başlıklar
    const hm = line.match(/^(#{1,4})\s+(.+)/);
    if (hm) {
      const level = hm[1].length;
      out.push(`<h${level}>${parseInline(hm[2])}</h${level}>`);
      i++; continue;
    }

    // Yatay çizgi
    if (/^---+$/.test(line.trim())) {
      out.push('<hr />');
      i++; continue;
    }

    // Alıntı
    if (line.startsWith('> ')) {
      const quoteLines: string[] = [];
      while (i < lines.length && lines[i].startsWith('> ')) {
        quoteLines.push(lines[i].slice(2));
        i++;
      }
      out.push(`<blockquote>${parseBlock(quoteLines)}</blockquote>`);
      continue;
    }

    // Sırasız liste
    if (/^[-*+]\s/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^[-*+]\s/.test(lines[i])) {
        items.push(`<li>${parseInline(lines[i].slice(2))}</li>`);
        i++;
      }
      out.push(`<ul>${items.join('')}</ul>`);
      continue;
    }

    // Sıralı liste
    if (/^\d+\.\s/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\d+\.\s/.test(lines[i])) {
        items.push(`<li>${parseInline(lines[i].replace(/^\d+\.\s/, ''))}</li>`);
        i++;
      }
      out.push(`<ol>${items.join('')}</ol>`);
      continue;
    }

    // Boş satır → paragraf ayracı
    if (line.trim() === '') {
      i++; continue;
    }

    // Paragraf: ardışık satırları birleştir
    const paraLines: string[] = [];
    while (i < lines.length && lines[i].trim() !== '' && !/^[#>*\-`]/.test(lines[i]) && !/^\d+\./.test(lines[i])) {
      paraLines.push(lines[i]);
      i++;
    }
    if (paraLines.length > 0) {
      out.push(`<p>${parseInline(paraLines.join(' '))}</p>`);
    }
  }

  return out.join('');
}

export const Markdown = ({ text, style }: Props) => {
  const html = parseBlock(text.split('\n'));
  return (
    <div
      className="md"
      style={style}
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
};
