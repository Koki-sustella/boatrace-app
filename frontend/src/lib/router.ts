type RouteHandler = (params: any) => Promise<void> | void;

interface Route {
  pattern: RegExp;
  keys: string[];
  handler: RouteHandler;
}

const routes: Route[] = [];

function compile(path: string): { pattern: RegExp; keys: string[] } {
  const keys: string[] = [];
  const pattern = path.replace(/:([a-zA-Z]+)/g, (_, key) => {
    keys.push(key);
    return "([^/]+)";
  });
  return { pattern: new RegExp(`^${pattern}$`), keys };
}

export function route(path: string, handler: RouteHandler) {
  const { pattern, keys } = compile(path);
  routes.push({ pattern, keys, handler });
}

let notFoundHandler: RouteHandler = () => {
  document.getElementById("app")!.innerHTML = "<p class='empty'>ページが見つかりません。</p>";
};

export function setNotFound(handler: RouteHandler) {
  notFoundHandler = handler;
}

async function resolve() {
  const hash = location.hash.replace(/^#/, "") || "/";
  const [path] = hash.split("?");
  for (const r of routes) {
    const m = path.match(r.pattern);
    if (m) {
      const params: Record<string, string> = {};
      r.keys.forEach((k, i) => (params[k] = decodeURIComponent(m[i + 1])));
      window.scrollTo(0, 0);
      await r.handler(params);
      return;
    }
  }
  await notFoundHandler({});
}

export function getQueryParams(): URLSearchParams {
  const hash = location.hash.replace(/^#/, "");
  const idx = hash.indexOf("?");
  return new URLSearchParams(idx >= 0 ? hash.slice(idx + 1) : "");
}

export function navigate(path: string) {
  location.hash = path;
}

export function startRouter() {
  window.addEventListener("hashchange", resolve);
  resolve();
}
