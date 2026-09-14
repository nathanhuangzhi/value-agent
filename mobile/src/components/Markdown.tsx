/**
 * Minimal Markdown renderer for chat replies — enough for what the model
 * actually emits: headings, bullet / numbered lists, paragraphs, **bold**,
 * `code`, and pipe tables (rendered as a horizontally-scrollable grid).
 * No dependency; anything fancier falls through as plain text.
 */
import { ScrollView, StyleSheet, Text, View, type TextStyle } from 'react-native';

import { useColors, fontSize, spacing } from '@/theme/colors';

type Block =
  | { kind: 'h'; level: number; text: string }
  | { kind: 'p'; text: string }
  | { kind: 'li'; ordered: boolean; marker: string; text: string }
  | { kind: 'table'; rows: string[][] }
  | { kind: 'code'; text: string };

function parse(md: string): Block[] {
  const lines = md.replace(/\r/g, '').split('\n');
  const blocks: Block[] = [];
  let para: string[] = [];
  let table: string[][] | null = null;
  let code: string[] | null = null;

  const flushPara = () => {
    if (para.length) blocks.push({ kind: 'p', text: para.join(' ') });
    para = [];
  };
  const flushTable = () => {
    if (table && table.length) blocks.push({ kind: 'table', rows: table });
    table = null;
  };

  for (const raw of lines) {
    const line = raw.trimEnd();
    if (code) {
      if (line.startsWith('```')) {
        blocks.push({ kind: 'code', text: code.join('\n') });
        code = null;
      } else code.push(raw);
      continue;
    }
    if (line.startsWith('```')) {
      flushPara(); flushTable(); code = [];
      continue;
    }
    if (/^\s*\|.*\|\s*$/.test(line)) {
      flushPara();
      const cells = line.trim().slice(1, -1).split('|').map((c) => c.trim());
      if (cells.every((c) => /^:?-{2,}:?$/.test(c))) continue; // separator row
      (table ??= []).push(cells);
      continue;
    }
    flushTable();
    const h = /^(#{1,4})\s+(.*)$/.exec(line);
    if (h) { flushPara(); blocks.push({ kind: 'h', level: h[1].length, text: h[2] }); continue; }
    const li = /^\s*([-*•]|\d+[.)])\s+(.*)$/.exec(line);
    if (li) {
      flushPara();
      const ordered = /\d/.test(li[1]);
      blocks.push({ kind: 'li', ordered, marker: ordered ? li[1].replace(')', '.') : '•', text: li[2] });
      continue;
    }
    if (!line.trim()) { flushPara(); continue; }
    para.push(line.trim());
  }
  if (code) blocks.push({ kind: 'code', text: code.join('\n') });
  flushPara(); flushTable();
  return blocks;
}

/** Inline **bold** and `code`; everything else verbatim. */
function Inline({ text, style }: { text: string; style: TextStyle }) {
  const c = useColors();
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).filter(Boolean);
  return (
    <Text style={style}>
      {parts.map((p, i) => {
        if (p.startsWith('**') && p.endsWith('**')) {
          return <Text key={i} style={{ fontWeight: '700' }}>{p.slice(2, -2)}</Text>;
        }
        if (p.startsWith('`') && p.endsWith('`')) {
          return (
            <Text key={i} style={{ fontFamily: 'Menlo', backgroundColor: c.surface, fontSize: (style.fontSize ?? 15) - 1 }}>
              {p.slice(1, -1)}
            </Text>
          );
        }
        return <Text key={i}>{p}</Text>;
      })}
    </Text>
  );
}

export function Markdown({ text, color }: { text: string; color: string }) {
  const c = useColors();
  const body: TextStyle = { color, fontSize: fontSize.md, lineHeight: 22 };
  const blocks = parse(text);
  return (
    <View>
      {blocks.map((b, i) => {
        switch (b.kind) {
          case 'h':
            return (
              <Inline
                key={i}
                text={b.text}
                style={{ ...body, fontWeight: '700', fontSize: b.level <= 2 ? fontSize.lg : fontSize.md, marginTop: i ? spacing.sm : 0, marginBottom: 2 }}
              />
            );
          case 'li':
            return (
              <View key={i} style={styles.li}>
                <Text style={[body, styles.marker]}>{b.marker}</Text>
                <View style={{ flex: 1 }}><Inline text={b.text} style={body} /></View>
              </View>
            );
          case 'code':
            return (
              <ScrollView key={i} horizontal style={[styles.code, { backgroundColor: c.surface, borderColor: c.border }]}>
                <Text style={{ color, fontFamily: 'Menlo', fontSize: fontSize.sm }}>{b.text}</Text>
              </ScrollView>
            );
          case 'table':
            return (
              <ScrollView key={i} horizontal style={styles.tableWrap}>
                <View>
                  {b.rows.map((row, r) => (
                    <View key={r} style={[styles.tr, { borderBottomColor: c.border }]}>
                      {row.map((cell, k) => (
                        <View key={k} style={[styles.td, k === 0 && styles.tdFirst]}>
                          <Inline text={cell} style={{ ...body, fontSize: fontSize.sm, lineHeight: 18, fontWeight: r === 0 ? '700' : '400' }} />
                        </View>
                      ))}
                    </View>
                  ))}
                </View>
              </ScrollView>
            );
          default:
            return <Inline key={i} text={b.text} style={{ ...body, marginBottom: spacing.sm }} />;
        }
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  li: { flexDirection: 'row', gap: spacing.sm, marginBottom: 2, paddingLeft: 2 },
  marker: { minWidth: 16 },
  code: { borderWidth: StyleSheet.hairlineWidth, borderRadius: 6, padding: spacing.sm, marginVertical: spacing.sm },
  tableWrap: { marginVertical: spacing.sm },
  tr: { flexDirection: 'row', borderBottomWidth: StyleSheet.hairlineWidth },
  td: { minWidth: 72, paddingVertical: 4, paddingHorizontal: 6, alignItems: 'flex-end' },
  tdFirst: { minWidth: 110, alignItems: 'flex-start' },
});
