import type { ShapeData } from "../../types/slide";
import { emuToPx, getMediaUrl } from "../../lib/slideUtils";
import TextBoxRenderer from "./TextBoxRenderer";
import ImageRenderer from "./ImageRenderer";
import TableRenderer from "./TableRenderer";
import ChartRenderer from "./ChartRenderer";
import AutoShapeRenderer from "./AutoShapeRenderer";
import GroupRenderer from "./GroupRenderer";

interface Props {
  shape: ShapeData;
  presentationId: number;
}

export default function ShapeRenderer({ shape, presentationId }: Props) {
  switch (shape.shape_type) {
    case "text_box":
      return <TextBoxRenderer shape={shape} />;
    case "image":
      return <ImageRenderer shape={shape} presentationId={presentationId} />;
    case "table":
      return <TableRenderer shape={shape} />;
    case "chart":
      return <ChartRenderer shape={shape} presentationId={presentationId} />;
    case "auto_shape":
      return <AutoShapeRenderer shape={shape} />;
    case "group":
      return <GroupRenderer shape={shape} presentationId={presentationId} />;
    case "media":
      return <MediaRenderer shape={shape} presentationId={presentationId} />;
    case "placeholder_unsupported":
      return <PlaceholderRenderer shape={shape} />;
    default:
      return null;
  }
}

function MediaRenderer({ shape, presentationId }: { shape: any; presentationId: number }) {
  const style: React.CSSProperties = {
    position: "absolute",
    left: emuToPx(shape.position.left_emu),
    top: emuToPx(shape.position.top_emu),
    width: emuToPx(shape.position.width_emu),
    height: emuToPx(shape.position.height_emu),
    zIndex: shape.z_order + 1,
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "#000",
    borderRadius: 4,
  };

  if (shape.media?.media_path) {
    return (
      <div style={style}>
        <video
          controls
          style={{ width: "100%", height: "100%" }}
          src={getMediaUrl(presentationId, shape.media.media_path)}
        />
      </div>
    );
  }

  return (
    <div style={{ ...style, backgroundColor: "#1e293b", color: "#94a3b8", fontSize: 14 }}>
      Video
    </div>
  );
}

function PlaceholderRenderer({ shape }: { shape: any }) {
  const style: React.CSSProperties = {
    position: "absolute",
    left: emuToPx(shape.position.left_emu),
    top: emuToPx(shape.position.top_emu),
    width: emuToPx(shape.position.width_emu),
    height: emuToPx(shape.position.height_emu),
    zIndex: shape.z_order + 1,
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "rgba(148, 163, 184, 0.1)",
    border: "1px dashed #cbd5e1",
    borderRadius: 4,
    color: "#94a3b8",
    fontSize: 12,
    padding: 8,
    textAlign: "center",
    overflow: "hidden",
  };

  return (
    <div style={style}>
      {shape.placeholder?.text || shape.placeholder?.label || ""}
    </div>
  );
}
