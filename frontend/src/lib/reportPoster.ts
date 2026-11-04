import type { GameReport } from "../api";

const POSTER_WIDTH = 1080;
const POSTER_HEIGHT = 1440;
const PAPER = "#f3f1e8";
const INK = "#17201e";
const MUTED = "#69736f";
const RED = "#dd3d33";
const TEAL = "#087c85";
const LINE = "#c6cbc3";

function roundedRect(
  context: CanvasRenderingContext2D,
  x: number,
  y: number,
  width: number,
  height: number,
  radius: number,
) {
  const safeRadius = Math.min(radius, width / 2, height / 2);
  context.beginPath();
  context.moveTo(x + safeRadius, y);
  context.lineTo(x + width - safeRadius, y);
  context.quadraticCurveTo(x + width, y, x + width, y + safeRadius);
  context.lineTo(x + width, y + height - safeRadius);
  context.quadraticCurveTo(
    x + width,
    y + height,
    x + width - safeRadius,
    y + height,
  );
  context.lineTo(x + safeRadius, y + height);
  context.quadraticCurveTo(x, y + height, x, y + height - safeRadius);
  context.lineTo(x, y + safeRadius);
  context.quadraticCurveTo(x, y, x + safeRadius, y);
  context.closePath();
}

function drawGrid(context: CanvasRenderingContext2D) {
  context.save();
  context.strokeStyle = "rgba(23, 32, 30, 0.055)";
  context.lineWidth = 1;
  for (let x = 0; x <= POSTER_WIDTH; x += 36) {
    context.beginPath();
    context.moveTo(x, 0);
    context.lineTo(x, POSTER_HEIGHT);
    context.stroke();
  }
  for (let y = 0; y <= POSTER_HEIGHT; y += 36) {
    context.beginPath();
    context.moveTo(0, y);
    context.lineTo(POSTER_WIDTH, y);
    context.stroke();
  }
  context.restore();
}

function wrapText(
  context: CanvasRenderingContext2D,
  text: string,
  maxWidth: number,
  maxLines: number,
) {
  const lines: string[] = [];
  let line = "";

  for (const character of Array.from(text)) {
    const nextLine = line + character;
    if (line && context.measureText(nextLine).width > maxWidth) {
      lines.push(line);
      line = character;
      if (lines.length === maxLines) {
        break;
      }
    } else {
      line = nextLine;
    }
  }

  if (lines.length < maxLines && line) {
    lines.push(line);
  }
  if (lines.length === maxLines) {
    const consumed = lines.join("").length;
    if (consumed < text.length) {
      let last = lines[maxLines - 1];
      while (
        last.length > 1 &&
        context.measureText(`${last}...`).width > maxWidth
      ) {
        last = last.slice(0, -1);
      }
      lines[maxLines - 1] = `${last.replace(/\.+$/, "")}...`;
    }
  }
  return lines;
}

function winnerTitle(report: GameReport) {
  if (report.winner === "A") {
    return "抽象派获胜";
  }
  if (report.winner === "B") {
    return "缝合派获胜";
  }
  return "世界线失衡";
}

function drawCurve(
  context: CanvasRenderingContext2D,
  values: number[],
  x: number,
  y: number,
  width: number,
  height: number,
) {
  const safeValues = values.length > 0 ? values : [50];
  const points = safeValues.map((value, index) => ({
    x: x + (index / Math.max(1, safeValues.length - 1)) * width,
    y: y + height - (Math.max(0, Math.min(100, value)) / 100) * height,
  }));

  context.save();
  roundedRect(context, x, y, width, height, 6);
  context.fillStyle = "#e2e5de";
  context.fill();

  context.strokeStyle = "rgba(23, 32, 30, 0.16)";
  context.setLineDash([8, 8]);
  context.beginPath();
  context.moveTo(x, y + height / 2);
  context.lineTo(x + width, y + height / 2);
  context.stroke();
  context.setLineDash([]);

  context.beginPath();
  points.forEach((point, index) => {
    if (index === 0) {
      context.moveTo(point.x, point.y);
    } else {
      context.lineTo(point.x, point.y);
    }
  });
  context.lineTo(points.at(-1)?.x ?? x + width, y + height);
  context.lineTo(points[0]?.x ?? x, y + height);
  context.closePath();
  context.fillStyle = "rgba(221, 61, 51, 0.13)";
  context.fill();

  context.beginPath();
  points.forEach((point, index) => {
    if (index === 0) {
      context.moveTo(point.x, point.y);
    } else {
      context.lineTo(point.x, point.y);
    }
  });
  context.strokeStyle = RED;
  context.lineWidth = 5;
  context.lineJoin = "round";
  context.stroke();

  for (const point of points) {
    context.beginPath();
    context.arc(point.x, point.y, 7, 0, Math.PI * 2);
    context.fillStyle = PAPER;
    context.fill();
    context.lineWidth = 4;
    context.strokeStyle = RED;
    context.stroke();
  }
  context.restore();
}

export function createReportPoster(report: GameReport, gameId = "") {
  const canvas = document.createElement("canvas");
  canvas.width = POSTER_WIDTH;
  canvas.height = POSTER_HEIGHT;
  const context = canvas.getContext("2d");
  if (!context) {
    throw new Error("当前浏览器不支持 Canvas");
  }

  context.fillStyle = PAPER;
  context.fillRect(0, 0, POSTER_WIDTH, POSTER_HEIGHT);
  drawGrid(context);

  context.fillStyle = INK;
  context.fillRect(0, 0, POSTER_WIDTH, 24);
  context.fillStyle = RED;
  context.fillRect(0, 24, 310, 8);
  context.fillStyle = TEAL;
  context.fillRect(310, 24, 190, 8);

  context.font =
    '800 22px "Cascadia Code", "SFMono-Regular", Consolas, monospace';
  context.fillStyle = INK;
  context.fillText("STITCH VS. ABSTRACT", 82, 96);
  context.fillStyle = MUTED;
  context.fillText("FINAL WORLD LINE REPORT / 05 ROUNDS", 82, 136);

  context.textAlign = "right";
  context.fillStyle = INK;
  context.fillText(gameId || "GAME COMPLETE", 998, 96);
  context.fillStyle = MUTED;
  context.fillText(
    new Intl.DateTimeFormat("zh-CN", { dateStyle: "long" }).format(new Date()),
    998,
    136,
  );
  context.textAlign = "left";

  context.fillStyle = report.winner === "B" ? TEAL : RED;
  roundedRect(context, 82, 190, 210, 42, 4);
  context.fill();
  context.fillStyle = "#ffffff";
  context.font = '800 18px "Microsoft YaHei UI", sans-serif';
  context.fillText(
    report.winner === "DRAW" ? "UNSTABLE DRAW" : `${report.winner} SIDE WINS`,
    105,
    218,
  );

  context.fillStyle = INK;
  context.font =
    '900 78px "Microsoft YaHei UI", "PingFang SC", sans-serif';
  context.fillText(winnerTitle(report), 78, 332);
  context.fillStyle = MUTED;
  context.font = '700 28px "Microsoft YaHei UI", "PingFang SC", sans-serif';
  context.fillText(report.verdict, 82, 382);

  context.fillStyle = RED;
  context.font =
    '900 86px "Cascadia Code", "SFMono-Regular", Consolas, monospace';
  context.fillText(String(report.score_a), 82, 500);
  context.fillStyle = TEAL;
  context.fillText(String(report.score_b), 580, 500);
  context.fillStyle = MUTED;
  context.font = '800 20px "Microsoft YaHei UI", sans-serif';
  context.fillText("ABSTRACT / A", 84, 535);
  context.fillText("STITCH / B", 582, 535);

  roundedRect(context, 78, 585, 924, 265, 8);
  context.fillStyle = "#ffffff";
  context.fill();
  context.strokeStyle = LINE;
  context.lineWidth = 2;
  context.stroke();
  context.fillStyle = MUTED;
  context.font =
    '800 18px "Cascadia Code", "SFMono-Regular", Consolas, monospace';
  context.fillText("FINAL STORY", 110, 628);
  context.fillStyle = INK;
  context.font =
    '800 39px "Microsoft YaHei UI", "PingFang SC", sans-serif';
  wrapText(context, report.final_story, 850, 4).forEach((line, index) => {
    context.fillText(line, 110, 688 + index * 56);
  });

  context.fillStyle = MUTED;
  context.font =
    '800 18px "Cascadia Code", "SFMono-Regular", Consolas, monospace';
  context.fillText("COLLAPSE CURVE", 82, 906);
  drawCurve(context, report.collapse_curve, 82, 932, 916, 132);
  context.fillStyle = INK;
  context.textAlign = "right";
  context.font =
    '900 40px "Cascadia Code", "SFMono-Regular", Consolas, monospace';
  context.fillText(
    String(report.collapse_curve.at(-1) ?? 50),
    998,
    1034,
  );
  context.textAlign = "left";

  context.fillStyle = INK;
  context.font =
    '800 20px "Cascadia Code", "SFMono-Regular", Consolas, monospace';
  context.fillText("AI COMMENTARY", 82, 1122);
  context.fillStyle = "#3f4946";
  context.font = '600 27px "Microsoft YaHei UI", "PingFang SC", sans-serif';
  wrapText(context, report.commentary, 910, 4).forEach((line, index) => {
    context.fillText(line, 82, 1170 + index * 44);
  });

  context.strokeStyle = LINE;
  context.lineWidth = 2;
  context.beginPath();
  context.moveTo(82, 1340);
  context.lineTo(998, 1340);
  context.stroke();
  context.fillStyle = MUTED;
  context.font =
    '800 17px "Cascadia Code", "SFMono-Regular", Consolas, monospace';
  context.fillText("MVP WORD", 82, 1382);
  context.fillText("STITCH SIGNATURE", 430, 1382);
  context.fillStyle = INK;
  context.font = '800 25px "Microsoft YaHei UI", sans-serif';
  context.fillText(report.poster.mvp_word || "N/A", 82, 1417);
  context.font = '600 21px "Microsoft YaHei UI", sans-serif';
  context.fillText(report.poster.best_comment || report.verdict, 430, 1417);

  return canvas;
}

export function downloadReportPoster(report: GameReport, gameId = "") {
  const canvas = createReportPoster(report, gameId);
  const anchor = document.createElement("a");
  const date = new Date().toISOString().slice(0, 10);
  anchor.download = `stitch-vs-abstract-report-${date}.png`;
  anchor.href = canvas.toDataURL("image/png");
  anchor.click();
}
