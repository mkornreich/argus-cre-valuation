// Small controlled inputs used across the sidebar panels.

// A numeric field. `scale` lets a field store a decimal while showing a human
// number — e.g. a percent field shows 8.25 and stores 0.0825 with scale={100}.
export function NumField({
  label,
  value,
  onChange,
  prefix,
  suffix,
  scale = 1,
  step = "any",
  min,
}) {
  const shown = value === null || value === undefined ? "" : value * scale;
  return (
    <label className="field">
      <span className="field-label">{label}</span>
      <span className="field-input">
        {prefix && <span className="affix">{prefix}</span>}
        <input
          type="number"
          step={step}
          min={min}
          value={shown}
          onChange={(e) => {
            const raw = e.target.value;
            onChange(raw === "" ? 0 : Number(raw) / scale);
          }}
        />
        {suffix && <span className="affix suffix">{suffix}</span>}
      </span>
    </label>
  );
}

export function TextField({ label, value, onChange }) {
  return (
    <label className="field">
      <span className="field-label">{label}</span>
      <span className="field-input">
        <input
          type="text"
          value={value ?? ""}
          onChange={(e) => onChange(e.target.value)}
        />
      </span>
    </label>
  );
}

export function Toggle({ label, checked, onChange }) {
  return (
    <label className="toggle">
      <input
        type="checkbox"
        checked={!!checked}
        onChange={(e) => onChange(e.target.checked)}
      />
      <span>{label}</span>
    </label>
  );
}
