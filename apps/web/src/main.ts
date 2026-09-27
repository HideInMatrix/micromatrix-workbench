import "./styles.css";

document.querySelector<HTMLElement>("#app")!.innerHTML = `
  <section class="shell">
    <p class="eyebrow">MICROMATRIX / PI BODY</p>
    <h1>Local MCP execution service</h1>
    <p class="lede">网页模型负责思考，Pi 插件负责在本机执行。</p>
    <dl>
      <div><dt>Runtime</dt><dd>TypeScript 7</dd></div>
      <div><dt>Frontend</dt><dd>Vite 8</dd></div>
      <div><dt>Pi core</dt><dd>v0.87.1</dd></div>
      <div><dt>MCP endpoint</dt><dd><code>/mcp</code></dd></div>
    </dl>
    <p class="note">当前页面只验证打包基座；服务控制接口将在 MCP 核心稳定后接入。</p>
  </section>
`;
