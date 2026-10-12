import { useEffect, useMemo, useRef, useState } from "react";
import Globe from "globe.gl";

type Model = {
  id: string;
  name: string;
  provider: string;
  resolution: string;
  step: string;
  status: string;
};

const fallbackModels: Model[] = [
  { id: "gfs", name: "GFS", provider: "NOAA / Open-Meteo", resolution: "0.25°", step: "1 小时", status: "ready" },
  { id: "ifs", name: "IFS", provider: "ECMWF / Open-Meteo", resolution: "0.25°", step: "1 小时", status: "ready" },
  { id: "aifs", name: "AIFS", provider: "ECMWF / Open-Meteo", resolution: "0.25°", step: "6 小时", status: "preview" },
  { id: "grapes", name: "GRAPES", provider: "CMA / Open-Meteo", resolution: "0.125°", step: "3 小时", status: "preview" },
];

const variables = [
  { id: "wind", label: "风场", unit: "m/s" },
  { id: "temperature", label: "温度", unit: "°C" },
  { id: "pressure", label: "气压", unit: "hPa" },
  { id: "precipitation", label: "降水", unit: "mm" },
];

const forecastSteps = ["现在", "+06h", "+12h", "+18h", "+24h", "+30h", "+36h", "+42h"];

function App() {
  const globeHostRef = useRef<HTMLDivElement>(null);
  const globeRef = useRef<any>(null);
  const [models, setModels] = useState<Model[]>(fallbackModels);
  const [modelId, setModelId] = useState("gfs");
  const [variableId, setVariableId] = useState("wind");
  const [step, setStep] = useState(0);
  const [isPlaying, setIsPlaying] = useState(true);
  const [boundaries, setBoundaries] = useState<unknown[]>([]);

  const selectedModel = useMemo(() => models.find((model) => model.id === modelId) ?? fallbackModels[0], [modelId, models]);
  const selectedVariable = variables.find((variable) => variable.id === variableId) ?? variables[0];

  useEffect(() => {
    fetch("/api/models")
      .then((response) => (response.ok ? response.json() : Promise.reject(new Error("模型接口不可用"))))
      .then((data: Model[]) => setModels(data))
      .catch(() => setModels(fallbackModels));

    fetch("/api/boundaries/provinces")
      .then((response) => (response.ok ? response.json() : Promise.reject(new Error("省界接口不可用"))))
      .then((data) => setBoundaries(data.features ?? []))
      .catch(() => setBoundaries([]));
  }, []);

  useEffect(() => {
    if (!isPlaying) return;
    const timer = window.setInterval(() => setStep((current) => (current + 1) % forecastSteps.length), 2200);
    return () => window.clearInterval(timer);
  }, [isPlaying]);

  useEffect(() => {
    if (!globeHostRef.current) return;
    const globe = new Globe(globeHostRef.current, { animateIn: true })
      .backgroundColor("#05070b")
      .globeImageUrl("https://unpkg.com/three-globe/example/img/earth-night.jpg")
      .bumpImageUrl("https://unpkg.com/three-globe/example/img/earth-topology.png")
      .showAtmosphere(true)
      .atmosphereColor("#4d8dff")
      .atmosphereAltitude(0.12)
      .showGraticules(false)
      .polygonsData(boundaries)
      .polygonCapColor(() => "rgba(33, 115, 183, 0.08)")
      .polygonSideColor(() => "rgba(82, 154, 217, 0.08)")
      .polygonStrokeColor(() => "rgba(138, 191, 246, 0.7)")
      .polygonAltitude(0.004)
      .width(globeHostRef.current.clientWidth)
      .height(globeHostRef.current.clientHeight);

    globe.controls().autoRotate = true;
    globe.controls().autoRotateSpeed = 0.18;
    globeRef.current = globe;

    const resize = () => {
      if (!globeHostRef.current || !globeRef.current) return;
      globe.width(globeHostRef.current.clientWidth).height(globeHostRef.current.clientHeight);
    };
    window.addEventListener("resize", resize);
    return () => {
      window.removeEventListener("resize", resize);
      globe._destructor?.();
      globeRef.current = null;
    };
  }, [boundaries]);

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand-lockup">
          <span className="brand-mark" />
          <span className="brand-name">METEO</span>
          <span className="brand-divider" />
          <span className="brand-section">全球天气态势</span>
        </div>
        <nav className="top-nav" aria-label="主导航">
          <button className="nav-item nav-item-active">天气场</button>
          <button className="nav-item">模型对比</button>
          <button className="nav-item">卫星云图</button>
        </nav>
        <div className="top-status"><span className="status-dot" />系统在线</div>
      </header>

      <main className="workspace">
        <section className="globe-stage">
          <div ref={globeHostRef} className="globe-canvas" />
          <div className="stage-vignette" />
          <div className="stage-readout">
            <div className="readout-live"><span className="readout-pulse" />实时视图</div>
            <div className="readout-title">{selectedVariable.label}<span>{selectedVariable.unit}</span></div>
            <div className="readout-meta">{selectedModel.name} · 预报时效 {forecastSteps[step]}</div>
          </div>
          <div className="coordinates"><span>经度 116.39°E</span><span>纬度 39.90°N</span></div>

          <aside className="control-panel">
            <div className="panel-heading"><span>天气场</span><span className="panel-kicker">CONTROL</span></div>

            <div className="control-group">
              <label className="control-label">数值模型</label>
              <div className="model-grid">
                {models.map((model) => (
                  <button key={model.id} className={`model-button ${model.id === modelId ? "selected" : ""}`} onClick={() => setModelId(model.id)}>
                    <span>{model.name}</span><small>{model.resolution}</small>
                  </button>
                ))}
              </div>
            </div>

            <div className="control-group">
              <label className="control-label">显示要素</label>
              <div className="variable-list">
                {variables.map((variable) => (
                  <button key={variable.id} className={`variable-button ${variable.id === variableId ? "selected" : ""}`} onClick={() => setVariableId(variable.id)}>
                    <span className={`variable-swatch swatch-${variable.id}`} />{variable.label}<span className="variable-unit">{variable.unit}</span>
                  </button>
                ))}
              </div>
            </div>

            <div className="control-group control-row">
              <div><label className="control-label">云图叠加</label><span className="control-value">Himawari-9</span></div>
              <button className="toggle is-on" aria-label="切换云图叠加"><span /></button>
            </div>
          </aside>
        </section>

        <section className="timeline-panel">
          <div className="timeline-topline">
            <div><span className="timeline-caption">预报时间</span><strong>2026 / 10 / 12</strong></div>
            <div className="timeline-model"><span className="model-badge">{selectedModel.name}</span><span>运行时间 12Z</span></div>
            <div className="timeline-clock">北京时间 16:42:08</div>
          </div>
          <div className="timeline-track-wrap">
            <button className="play-button" onClick={() => setIsPlaying((playing) => !playing)} aria-label={isPlaying ? "暂停" : "播放"}>{isPlaying ? "Ⅱ" : "▶"}</button>
            <div className="timeline-track">
              <div className="track-line" /><div className="track-progress" style={{ width: `${(step / (forecastSteps.length - 1)) * 100}%` }} />
              {forecastSteps.map((label, index) => (
                <button key={label} className={`time-point ${index === step ? "active" : ""}`} style={{ left: `${(index / (forecastSteps.length - 1)) * 100}%` }} onClick={() => { setStep(index); setIsPlaying(false); }}>
                  <span className="point-dot" /><span className="point-label">{label}</span>
                </button>
              ))}
            </div>
          </div>
          <div className="timeline-footer"><span>数据源 · Open-Meteo Open Data</span><span>最后更新 16:30</span><span className="footer-live">自动播放已开启</span></div>
        </section>
      </main>
    </div>
  );
}

export default App;
