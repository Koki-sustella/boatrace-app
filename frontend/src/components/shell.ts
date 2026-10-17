export function renderShell(opts: { title: string; back?: boolean; activeNav?: string }): HTMLElement {
  const app = document.getElementById("app")!;
  app.innerHTML = `
    <header class="header">
      ${opts.back ? `<button class="back-btn" id="back-btn" aria-label="戻る">←</button>` : ""}
      <h1>${opts.title}</h1>
    </header>
    <main class="content" id="content"></main>
    <nav class="nav-bar">
      <a href="#/search" data-nav="search"><span class="icon">🔍</span>選手検索</a>
      <a href="#/venue-course" data-nav="venue-course"><span class="icon">📍</span>場×コース</a>
      <a href="#/ranking" data-nav="ranking"><span class="icon">📈</span>伸び率</a>
    </nav>
  `;
  if (opts.back) {
    document.getElementById("back-btn")!.addEventListener("click", () => history.back());
  }
  if (opts.activeNav) {
    const el = app.querySelector(`[data-nav="${opts.activeNav}"]`);
    el?.classList.add("active");
  }
  return document.getElementById("content")!;
}

export function loading(el: HTMLElement) {
  el.innerHTML = `<div class="loading">読み込み中…</div>`;
}
