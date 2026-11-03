interface CollapseMeterProps {
  value: number;
}

function collapseLabel(value: number): string {
  if (value >= 75) {
    return "临界崩坏";
  }
  if (value >= 55) {
    return "结构松动";
  }
  if (value <= 30) {
    return "强行稳定";
  }
  return "动态平衡";
}

export function CollapseMeter({ value }: CollapseMeterProps) {
  const safeValue = Math.max(0, Math.min(100, value));

  return (
    <section className="collapse-panel" aria-labelledby="collapse-label">
      <div className="collapse-heading">
        <span id="collapse-label">崩坏度</span>
        <strong>{safeValue}</strong>
        <span className="collapse-state">{collapseLabel(safeValue)}</span>
      </div>
      <div
        className="collapse-track"
        role="progressbar"
        aria-label="崩坏度"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={safeValue}
      >
        <span
          className="collapse-fill"
          style={{ width: `${safeValue}%` }}
        />
        <span className="collapse-midline" />
      </div>
      <div className="collapse-scale" aria-hidden="true">
        <span>逻辑</span>
        <span>50</span>
        <span>抽象</span>
      </div>
    </section>
  );
}
