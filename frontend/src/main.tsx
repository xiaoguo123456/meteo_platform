import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
// 数字字体随站点自托管；Google Fonts 在国内不通，且 CSS @import 会阻塞样式生效。
import "@fontsource/dm-mono/latin-400.css";
import "@fontsource/dm-mono/latin-500.css";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
