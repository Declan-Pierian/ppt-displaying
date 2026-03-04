const EMU_PER_INCH = 914400;
const DEFAULT_DPI = 96;

export function emuToPx(emu: number, dpi: number = DEFAULT_DPI): number {
  return (emu / EMU_PER_INCH) * dpi;
}

export function emuToPt(emu: number): number {
  return emu / 12700;
}

export function getMediaUrl(presentationId: number, mediaPath: string | null): string {
  if (!mediaPath) return "";
  // mediaPath looks like "media/filename.png"
  return `/api/v1/media/${presentationId}/${mediaPath.replace("media/", "")}`;
}

export function getFillStyle(fill: {
  type: string;
  color?: string;
  gradient_stops?: Array<{ color: string; position: number }>;
  angle_degrees?: number | null;
}): React.CSSProperties {
  if (!fill || fill.type === "none") return {};

  if (fill.type === "solid" && fill.color) {
    return { backgroundColor: fill.color };
  }

  if (fill.type === "gradient" && fill.gradient_stops?.length) {
    const angle = fill.angle_degrees ?? 180;
    const stops = fill.gradient_stops
      .map((s) => `${s.color} ${Math.round(s.position * 100)}%`)
      .join(", ");
    return { background: `linear-gradient(${angle}deg, ${stops})` };
  }

  return {};
}

export function getBorderStyle(border: {
  color: string | null;
  width_pt: number | null;
  dash_style: string | null;
}): React.CSSProperties {
  if (!border?.color || !border?.width_pt) return {};

  let style = "solid";
  if (border.dash_style) {
    const d = border.dash_style.toLowerCase();
    if (d.includes("dash")) style = "dashed";
    if (d.includes("dot")) style = "dotted";
  }

  return {
    border: `${border.width_pt}pt ${style} ${border.color}`,
  };
}

export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleString();
}
