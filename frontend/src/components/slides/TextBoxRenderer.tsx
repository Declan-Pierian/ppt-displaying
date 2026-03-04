import type { CSSProperties } from "react";
import type { TextBoxShape, ParagraphData, TextRun } from "../../types/slide";
import { emuToPx, getFillStyle, getBorderStyle } from "../../lib/slideUtils";

interface Props {
  shape: TextBoxShape;
}

export default function TextBoxRenderer({ shape }: Props) {
  const containerStyle: CSSProperties = {
    position: "absolute",
    left: emuToPx(shape.position.left_emu),
    top: emuToPx(shape.position.top_emu),
    width: emuToPx(shape.position.width_emu),
    height: emuToPx(shape.position.height_emu),
    zIndex: shape.z_order + 1,
    transform: shape.rotation_degrees ? `rotate(${shape.rotation_degrees}deg)` : undefined,
    overflow: "hidden",
    wordWrap: "break-word",
    ...getFillStyle(shape.fill),
    ...getBorderStyle(shape.border),
  };

  if (!shape.text_body?.paragraphs?.length) return <div style={containerStyle} />;

  return (
    <div style={containerStyle}>
      {shape.text_body.paragraphs.map((para, i) => (
        <ParagraphRenderer key={i} paragraph={para} />
      ))}
    </div>
  );
}

function ParagraphRenderer({ paragraph }: { paragraph: ParagraphData }) {
  const pStyle: CSSProperties = {
    textAlign: (paragraph.alignment as any) || "left",
    lineHeight: paragraph.line_spacing_pt ? `${paragraph.line_spacing_pt * 1.2}pt` : "1.35",
    marginTop: paragraph.space_before_pt ? `${paragraph.space_before_pt}pt` : 0,
    marginBottom: paragraph.space_after_pt ? `${paragraph.space_after_pt}pt` : 0,
    paddingLeft: paragraph.level ? `${paragraph.level * 28}px` : undefined,
    margin: 0,
    minHeight: paragraph.runs.length === 0 ? "0.5em" : undefined,
  };

  // Empty paragraph = line break
  if (!paragraph.runs.length) {
    return <p style={pStyle}>&nbsp;</p>;
  }

  return (
    <p style={pStyle}>
      {paragraph.bullet && <BulletRenderer bullet={paragraph.bullet} />}
      {paragraph.runs.map((run, j) => (
        <RunRenderer key={j} run={run} />
      ))}
    </p>
  );
}

function RunRenderer({ run }: { run: TextRun }) {
  const font = run.font;

  const style: CSSProperties = {
    fontFamily: font.name ? `"${font.name}", Calibri, Arial, sans-serif` : "Calibri, Arial, sans-serif",
    fontSize: font.size_pt ? `${font.size_pt}pt` : undefined,
    fontWeight: font.bold ? "bold" : "normal",
    fontStyle: font.italic ? "italic" : "normal",
    textDecoration: [
      font.underline ? "underline" : "",
      font.strikethrough ? "line-through" : "",
    ]
      .filter(Boolean)
      .join(" ") || undefined,
    color: font.color || undefined,
    whiteSpace: "pre-wrap",
  };

  if (run.hyperlink) {
    return (
      <a
        href={run.hyperlink.url}
        target="_blank"
        rel="noopener noreferrer"
        style={{
          ...style,
          color: font.color || "#0563C1",
          textDecoration: "underline",
          cursor: "pointer",
        }}
      >
        {run.text}
      </a>
    );
  }

  return <span style={style}>{run.text}</span>;
}

function BulletRenderer({ bullet }: { bullet: { type: string; char?: string } }) {
  const char = bullet.type === "char" ? bullet.char || "\u2022" : "";
  return <span style={{ marginRight: 8 }}>{char}</span>;
}
