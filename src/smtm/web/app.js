const state = {
  activeRunId: null,
  pollTimer: null,
  marketTimer: null,
  accountTimer: null,
  latestSnapshot: null,
  latestMarketSnapshot: null,
  latestAccountSnapshot: null,
  controlsBusy: false,
  clientMarketPoints: {
    "KRW-BTC": [],
    "KRW-XRP": [],
  },
};

const els = {
  configSelect: document.getElementById("configSelect"),
  tickDelay: document.getElementById("tickDelay"),
  marketInterval: document.getElementById("marketInterval"),
  startButton: document.getElementById("startButton"),
  stopButton: document.getElementById("stopButton"),
  serverState: document.getElementById("serverState"),
  lastTick: document.getElementById("lastTick"),
  progressValue: document.getElementById("progressValue"),
  progressBar: document.getElementById("progressBar"),
  assetValue: document.getElementById("assetValue"),
  initialValue: document.getElementById("initialValue"),
  returnValue: document.getElementById("returnValue"),
  drawdownValue: document.getElementById("drawdownValue"),
  orderValue: document.getElementById("orderValue"),
  fillRejectValue: document.getElementById("fillRejectValue"),
  runId: document.getElementById("runId"),
  reportLink: document.getElementById("reportLink"),
  tickCount: document.getElementById("tickCount"),
  startedAt: document.getElementById("startedAt"),
  endedAt: document.getElementById("endedAt"),
  outputPath: document.getElementById("outputPath"),
  fillCount: document.getElementById("fillCount"),
  eventCount: document.getElementById("eventCount"),
  fillsBody: document.getElementById("fillsBody"),
  eventsBody: document.getElementById("eventsBody"),
  chart: document.getElementById("equityChart"),
  btcState: document.getElementById("btcMarketState"),
  btcPrice: document.getElementById("btcPrice"),
  btcChange: document.getElementById("btcChange"),
  btcUpdated: document.getElementById("btcUpdated"),
  btcChart: document.getElementById("btcChart"),
  xrpState: document.getElementById("xrpMarketState"),
  xrpPrice: document.getElementById("xrpPrice"),
  xrpChange: document.getElementById("xrpChange"),
  xrpUpdated: document.getElementById("xrpUpdated"),
  xrpChart: document.getElementById("xrpChart"),
  accountState: document.getElementById("accountState"),
  tradingMode: document.getElementById("tradingMode"),
  accountTotalValue: document.getElementById("accountTotalValue"),
  accountKrwValue: document.getElementById("accountKrwValue"),
  maxOrderValue: document.getElementById("maxOrderValue"),
  holdingsBody: document.getElementById("holdingsBody"),
  orderMode: document.getElementById("orderMode"),
  orderMarket: document.getElementById("orderMarket"),
  orderSide: document.getElementById("orderSide"),
  orderKind: document.getElementById("orderKind"),
  orderPrice: document.getElementById("orderPrice"),
  orderVolume: document.getElementById("orderVolume"),
  orderPriceLabel: document.getElementById("orderPriceLabel"),
  orderVolumeLabel: document.getElementById("orderVolumeLabel"),
  testOrderButton: document.getElementById("testOrderButton"),
  submitOrderButton: document.getElementById("submitOrderButton"),
  orderResult: document.getElementById("orderResult"),
};

const chartHoverState = new WeakMap();
const ACTIVE_RUN_STATES = new Set(["READY", "RUNNING", "PAUSED", "STOPPING"]);
const DASHBOARD_CACHE_KEY = "smtm.dashboard.cache.v1";
const MARKET_CODES = ["KRW-BTC", "KRW-XRP"];
let chartTooltip = null;

async function getJson(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const contentType = response.headers.get("Content-Type") || "";
  const rawText = await response.text();
  let payload = {};
  if (rawText && contentType.includes("application/json")) {
    try {
      payload = JSON.parse(rawText);
    } catch (error) {
      throw new Error(`JSON 응답 해석 실패: ${error.message}`);
    }
  } else if (rawText && rawText.trim().startsWith("{")) {
    try {
      payload = JSON.parse(rawText);
    } catch (error) {
      throw new Error(`JSON 응답 해석 실패: ${error.message}`);
    }
  } else if (rawText) {
    const textPreview = rawText.replace(/\s+/g, " ").slice(0, 80);
    throw new Error(`서버가 JSON이 아닌 응답을 반환했습니다. 최신 서버를 다시 시작해 주세요. (${response.status} ${textPreview})`);
  }
  if (!response.ok && !contentType.includes("application/json")) {
    throw new Error(`서버 API 응답이 JSON이 아닙니다. 최신 서버를 다시 시작해 주세요. (${response.status} ${response.statusText})`);
  }
  if (!response.ok) {
    throw new Error(payload.error || response.statusText);
  }
  return payload;
}

async function loadConfigs() {
  const payload = await getJson("/api/configs");
  els.configSelect.innerHTML = "";
  payload.configs.forEach((config) => {
    const option = document.createElement("option");
    option.value = config.name;
    option.textContent = config.title;
    els.configSelect.appendChild(option);
  });
}

async function startRun() {
  if (els.startButton.disabled) return;
  setBusy(true);
  try {
    resetClientMarketPoints();
    const snapshot = await getJson("/api/runs", {
      method: "POST",
      body: JSON.stringify({
        config_name: els.configSelect.value,
        tick_delay: Number(els.tickDelay.value || 0),
        market_interval: Number(els.marketInterval.value || 3),
      }),
    });
    state.activeRunId = snapshot.run_id;
    render(snapshot);
    beginRunPolling();
    beginMarketPolling();
  } catch (error) {
    showError(error.message);
  } finally {
    setBusy(false);
  }
}

async function stopRun() {
  if (!state.activeRunId || els.stopButton.disabled) return;
  setBusy(true);
  try {
    const snapshot = await getJson(`/api/runs/${state.activeRunId}/stop`, { method: "POST" });
    render(snapshot);
    if (state.marketTimer) {
      clearInterval(state.marketTimer);
      state.marketTimer = null;
    }
  } catch (error) {
    showError(error.message);
  } finally {
    setBusy(false);
  }
}

function beginRunPolling() {
  if (state.pollTimer) clearInterval(state.pollTimer);
  state.pollTimer = setInterval(refreshRun, 750);
  refreshRun();
}

function beginMarketPolling() {
  if (state.marketTimer) clearInterval(state.marketTimer);
  state.marketTimer = setInterval(refreshMarkets, 1000);
  refreshMarkets();
}

function beginAccountPolling() {
  if (state.accountTimer) clearInterval(state.accountTimer);
  state.accountTimer = setInterval(refreshAccount, 5000);
  refreshAccount();
}

async function refreshRun() {
  if (!state.activeRunId) return;
  try {
    const snapshot = await getJson(`/api/runs/${state.activeRunId}`);
    render(snapshot);
    if (["STOPPED", "ERROR"].includes(snapshot.state) && state.pollTimer) {
      clearInterval(state.pollTimer);
      state.pollTimer = null;
    }
  } catch (error) {
    showError(error.message);
  }
}

async function refreshMarkets() {
  try {
    const snapshot = await getJson("/api/markets");
    if (marketSnapshotHasPrices(snapshot)) {
      state.latestMarketSnapshot = snapshot;
      hydrateClientMarketPoints(snapshot);
      renderMarketSnapshot(snapshot);
      persistDashboardState();
      return;
    }
    const fallback = await fetchClientMarketSnapshot(snapshot?.error);
    state.latestMarketSnapshot = fallback;
    renderMarketSnapshot(fallback);
    persistDashboardState();
  } catch (error) {
    try {
      const fallback = await fetchClientMarketSnapshot(error.message);
      state.latestMarketSnapshot = fallback;
      renderMarketSnapshot(fallback);
      persistDashboardState();
    } catch (fallbackError) {
      state.latestMarketSnapshot = {
        ...(state.latestMarketSnapshot || {}),
        error: fallbackError.message,
        markets: state.latestMarketSnapshot?.markets || {},
      };
      renderMarketSnapshot(state.latestMarketSnapshot);
      persistDashboardState();
    }
  }
}

async function refreshAccount() {
  try {
    const snapshot = await getJson("/api/account");
    state.latestAccountSnapshot = snapshot;
    renderAccount(snapshot);
  } catch (error) {
    const snapshot = {
      error: error.message,
      accounts: [],
      api_configured: false,
      live_trading_enabled: false,
      mode: "가상 주문",
      allowed_markets: MARKET_CODES,
    };
    state.latestAccountSnapshot = snapshot;
    renderAccount(snapshot);
  }
}

async function testManualOrder() {
  await sendManualOrder("/api/orders/test", "POST");
}

async function submitManualOrder() {
  const isLive = Boolean(state.latestAccountSnapshot?.live_trading_enabled);
  if (isLive && !confirm("실제 주문을 전송합니다. 계속할까요?")) return;
  await sendManualOrder("/api/orders", "POST");
}

async function sendManualOrder(url, method) {
  setOrderBusy(true);
  try {
    const payload = manualOrderPayload();
    const result = await getJson(url, {
      method,
      body: JSON.stringify(payload),
    });
    renderOrderResult(result);
    refreshAccount();
  } catch (error) {
    renderOrderResult({ status: "error", reason: error.message });
  } finally {
    setOrderBusy(false);
  }
}

async function fetchClientMarketSnapshot(serverError) {
  if (!state.clientMarketPoints["KRW-BTC"].length || !state.clientMarketPoints["KRW-XRP"].length) {
    await seedClientMarketHistory();
  }
  const response = await fetch("https://api.upbit.com/v1/ticker?markets=KRW-BTC,KRW-XRP", {
    headers: { Accept: "application/json" },
  });
  if (!response.ok) {
    throw new Error(`브라우저 시세 조회 실패: ${response.status}`);
  }
  const payload = await response.json();
  if (!Array.isArray(payload)) {
    throw new Error("브라우저 시세 응답 형식이 올바르지 않습니다.");
  }
  const now = new Date().toISOString();
  payload.forEach((item) => {
    const market = item.market;
    if (!state.clientMarketPoints[market]) return;
    state.clientMarketPoints[market].push({
      market,
      name: market === "KRW-BTC" ? "비트코인" : "엑스알피(리플)",
      date_time: now,
      trade_price: item.trade_price,
      trade_volume: item.trade_volume,
      signed_change_rate: item.signed_change_rate,
      signed_change_price: item.signed_change_price,
      acc_trade_price_24h: item.acc_trade_price_24h,
      acc_trade_volume_24h: item.acc_trade_volume_24h,
    });
    state.clientMarketPoints[market] = state.clientMarketPoints[market].slice(-240);
  });
  return {
    started_at: now,
    last_updated_at: now,
    last_attempt_at: now,
    running: true,
    error: null,
    fallback_from_browser: Boolean(serverError),
    markets: {
      "KRW-BTC": clientMarketItem("KRW-BTC", "비트코인"),
      "KRW-XRP": clientMarketItem("KRW-XRP", "엑스알피(리플)"),
    },
  };
}

async function seedClientMarketHistory() {
  const markets = ["KRW-BTC", "KRW-XRP"];
  const histories = await Promise.all(
    markets.map(async (market) => {
      const response = await fetch(
        `https://api.upbit.com/v1/candles/minutes/1?market=${encodeURIComponent(market)}&count=60`,
        { headers: { Accept: "application/json" } },
      );
      if (!response.ok) {
        throw new Error(`최근 1시간 분봉 조회 실패: ${response.status}`);
      }
      const payload = await response.json();
      if (!Array.isArray(payload)) {
        throw new Error("최근 1시간 분봉 응답 형식이 올바르지 않습니다.");
      }
      return {
        market,
        points: payload
          .slice()
          .reverse()
          .map((item) => ({
            market,
            name: market === "KRW-BTC" ? "비트코인" : "엑스알피(리플)",
            date_time: normalizeUpbitCandleTime(item.candle_date_time_utc || item.candle_date_time_kst),
            trade_price: item.trade_price,
            trade_volume: item.candle_acc_trade_volume,
            signed_change_rate: null,
            signed_change_price: null,
            acc_trade_price_24h: null,
            acc_trade_volume_24h: item.candle_acc_trade_volume,
            source: "minute_candle",
          })),
      };
    }),
  );
  histories.forEach(({ market, points }) => {
    state.clientMarketPoints[market] = points.slice(-240);
  });
}

function clientMarketItem(market, name) {
  const points = state.clientMarketPoints[market] || [];
  return {
    market,
    name,
    points,
    latest: points.length ? points[points.length - 1] : null,
  };
}

function marketSnapshotHasPrices(snapshot) {
  const markets = snapshot?.markets || {};
  return Boolean(markets["KRW-BTC"]?.latest && markets["KRW-XRP"]?.latest);
}

function resetClientMarketPoints() {
  state.clientMarketPoints = emptyClientMarketPoints();
}

function emptyClientMarketPoints() {
  return {
    "KRW-BTC": [],
    "KRW-XRP": [],
  };
}

function hydrateClientMarketPoints(snapshot) {
  const markets = snapshot?.markets || {};
  MARKET_CODES.forEach((market) => {
    const points = markets[market]?.points;
    if (Array.isArray(points) && points.length > 0) {
      state.clientMarketPoints[market] = points.slice(-240);
    }
  });
}

function normalizeClientMarketPoints(pointsByMarket) {
  const normalized = emptyClientMarketPoints();
  MARKET_CODES.forEach((market) => {
    const points = pointsByMarket?.[market];
    normalized[market] = Array.isArray(points) ? points.slice(-240) : [];
  });
  return normalized;
}

function restoreDashboardState() {
  let cached = null;
  try {
    cached = JSON.parse(localStorage.getItem(DASHBOARD_CACHE_KEY) || "null");
  } catch (error) {
    return;
  }
  if (!cached || typeof cached !== "object") return;

  state.clientMarketPoints = normalizeClientMarketPoints(cached.clientMarketPoints);
  if (cached.latestMarketSnapshot) {
    state.latestMarketSnapshot = cached.latestMarketSnapshot;
    hydrateClientMarketPoints(cached.latestMarketSnapshot);
  }
  if (cached.latestSnapshot) {
    state.activeRunId = cached.activeRunId || cached.latestSnapshot.run_id || null;
    render(cached.latestSnapshot);
    if (state.activeRunId && ACTIVE_RUN_STATES.has(cached.latestSnapshot.state)) {
      beginRunPolling();
      beginMarketPolling();
    }
    return;
  }
  renderMarketSnapshot(state.latestMarketSnapshot);
  updateRunControls();
}

function persistDashboardState() {
  try {
    localStorage.setItem(
      DASHBOARD_CACHE_KEY,
      JSON.stringify({
        activeRunId: state.activeRunId,
        latestSnapshot: state.latestSnapshot,
        latestMarketSnapshot: state.latestMarketSnapshot,
        clientMarketPoints: state.clientMarketPoints,
        savedAt: new Date().toISOString(),
      }),
    );
  } catch (error) {
    // Storage can be unavailable in hardened browser modes; the live dashboard still works.
  }
}

function normalizeUpbitCandleTime(value) {
  if (!value) return new Date().toISOString();
  const text = String(value);
  if (text.includes("+") || text.endsWith("Z")) return text;
  return `${text}+00:00`;
}

async function loadLatestRun() {
  const payload = await getJson("/api/runs");
  if (payload.runs.length === 0) {
    state.activeRunId = null;
    if (state.latestSnapshot && ACTIVE_RUN_STATES.has(state.latestSnapshot.state)) {
      render({
        ...state.latestSnapshot,
        state: "STOPPED",
        ended_at: state.latestSnapshot.ended_at || new Date().toISOString(),
      });
    } else {
      updateRunControls();
    }
    return;
  }
  const latest = payload.runs[payload.runs.length - 1];
  state.activeRunId = latest.run_id;
  render(latest);
  if (ACTIVE_RUN_STATES.has(latest.state)) {
    beginRunPolling();
    beginMarketPolling();
  }
}

function render(snapshot) {
  state.latestSnapshot = snapshot;
  const report = snapshot.report || {};
  const progress = Math.round((snapshot.progress_ratio || 0) * 100);
  const currentTick = snapshot.current_tick || 0;
  const totalTicks = snapshot.total_ticks || 0;
  const isContinuous = Boolean(snapshot.is_continuous);

  els.serverState.textContent = statusLabel(snapshot.state);
  els.serverState.className = `pill ${String(snapshot.state || "idle").toLowerCase()}`;
  els.lastTick.textContent = snapshot.last_tick_at ? formatDate(snapshot.last_tick_at) : "틱 없음";
  els.progressValue.textContent = isContinuous ? `${currentTick.toLocaleString()}틱` : `${progress}%`;
  els.progressBar.style.width = isContinuous
    ? `${Math.max(8, currentTick % 100)}%`
    : `${Math.max(0, Math.min(progress, 100))}%`;
  els.assetValue.textContent = money(report.final_asset_value);
  els.initialValue.textContent = `초기 자산 ${money(report.initial_asset_value)}`;
  els.returnValue.textContent = percent(report.cumulative_return);
  els.returnValue.className = Number(report.cumulative_return || 0) >= 0 ? "positive" : "negative";
  els.drawdownValue.textContent = `최대 낙폭 ${percent(report.max_drawdown)}`;
  els.orderValue.textContent = String(report.order_result_count || 0);
  els.fillRejectValue.textContent = `체결 ${report.fill_count || 0}건, 거절 ${report.reject_count || 0}건`;
  els.runId.textContent = snapshot.run_id || "실행 없음";
  els.tickCount.textContent = isContinuous
    ? `${currentTick.toLocaleString()} / 원본 ${snapshot.source_tick_count || 0} 반복`
    : totalTicks
      ? `${currentTick} / ${totalTicks}`
      : `${currentTick}`;
  els.startedAt.textContent = snapshot.started_at ? formatDate(snapshot.started_at) : "-";
  els.endedAt.textContent = snapshot.ended_at ? formatDate(snapshot.ended_at) : "-";
  els.outputPath.textContent = snapshot.report_write_error ? "메모리 보관" : snapshot.output_path || "-";
  els.reportLink.href = snapshot.run_id ? `/api/runs/${snapshot.run_id}/report` : "#";
  els.fillCount.textContent = String((snapshot.fills || []).length);
  els.eventCount.textContent = String((snapshot.recent_events || []).length);
  updateRunControls(snapshot);

  renderFills(snapshot.fills || []);
  renderEvents(snapshot.recent_events || []);
  renderMarketSnapshot(state.latestMarketSnapshot);
  drawEquityChart(snapshot.equity_points || []);
  persistDashboardState();
}

function renderAccount(snapshot) {
  const accounts = snapshot?.accounts || [];
  const hasError = Boolean(snapshot?.error);
  const configured = Boolean(snapshot?.api_configured);
  els.accountState.textContent = hasError ? "조회 오류" : configured ? "조회 완료" : "API 키 없음";
  els.accountState.title = snapshot?.error || "";
  els.tradingMode.textContent = snapshot?.mode || "가상 주문";
  els.orderMode.textContent = snapshot?.live_trading_enabled ? "실거래 활성" : "가상 주문";
  els.orderMode.className = snapshot?.live_trading_enabled ? "muted negative" : "muted";
  els.accountTotalValue.textContent = money(snapshot?.total_krw);
  els.accountKrwValue.textContent = money(snapshot?.available_krw);
  els.maxOrderValue.textContent = money(snapshot?.max_order_krw);
  renderAllowedMarkets(snapshot?.allowed_markets || MARKET_CODES);
  renderHoldings(accounts, configured, hasError, snapshot?.error);
}

function renderAllowedMarkets(markets) {
  const allowedMarkets = Array.isArray(markets) && markets.length > 0 ? markets : MARKET_CODES;
  const selected = els.orderMarket.value;
  els.orderMarket.innerHTML = "";
  allowedMarkets.forEach((market) => {
    const option = document.createElement("option");
    option.value = market;
    option.textContent = marketLabel(market);
    els.orderMarket.appendChild(option);
  });
  if (allowedMarkets.includes(selected)) {
    els.orderMarket.value = selected;
  } else {
    els.orderMarket.value = allowedMarkets[0] || "";
  }
  updateOrderForm();
}

function renderHoldings(accounts, configured, hasError, errorMessage) {
  els.holdingsBody.innerHTML = "";
  if (hasError) {
    els.holdingsBody.appendChild(emptyRow(5, errorMessage || "계좌 조회 오류"));
    return;
  }
  if (!configured) {
    els.holdingsBody.appendChild(emptyRow(5, ".env API Key 미설정"));
    return;
  }
  if (accounts.length === 0) {
    els.holdingsBody.appendChild(emptyRow(5, "보유 자산 없음"));
    return;
  }
  accounts.forEach((account) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${escapeHtml(account.currency || "-")}</td>
      <td>${number(account.balance)}</td>
      <td>${number(account.locked)}</td>
      <td>${money(account.avg_buy_price)}</td>
      <td>${money(account.valuation_krw)}</td>
    `;
    els.holdingsBody.appendChild(tr);
  });
}

function manualOrderPayload() {
  const orderKind = els.orderKind.value;
  const side = orderKind === "market_buy" ? "buy" : orderKind === "market_sell" ? "sell" : els.orderSide.value;
  return {
    market: els.orderMarket.value,
    side,
    order_kind: orderKind,
    price: els.orderPrice.disabled ? "" : els.orderPrice.value,
    volume: els.orderVolume.disabled ? "" : els.orderVolume.value,
  };
}

function renderOrderResult(result) {
  const status = result?.status || "-";
  const reason = result?.reason || result?.error || "";
  const mode = result?.mode ? `${result.mode} / ` : "";
  const orderId = result?.exchange_order_id ? ` / ${result.exchange_order_id}` : "";
  els.orderResult.textContent = `${mode}${status}${orderId}${reason ? ` / ${reason}` : ""}`;
  els.orderResult.className = status === "error" ? "order-result negative" : "order-result muted";
}

function updateOrderForm() {
  const orderKind = els.orderKind.value;
  const isMarketBuy = orderKind === "market_buy";
  const isMarketSell = orderKind === "market_sell";
  if (isMarketBuy) {
    els.orderSide.value = "buy";
    els.orderSide.disabled = true;
  } else if (isMarketSell) {
    els.orderSide.value = "sell";
    els.orderSide.disabled = true;
  } else {
    els.orderSide.disabled = false;
  }
  els.orderPrice.disabled = isMarketSell;
  els.orderVolume.disabled = isMarketBuy;
  els.orderPriceLabel.textContent = isMarketBuy ? "주문금액" : "가격";
  els.orderVolumeLabel.textContent = isMarketSell ? "매도수량" : "수량";
}

function setOrderBusy(enabled) {
  els.testOrderButton.disabled = enabled;
  els.submitOrderButton.disabled = enabled;
}

function renderFills(fills) {
  els.fillsBody.innerHTML = "";
  const rows = fills.slice(-12).reverse();
  if (rows.length === 0) {
    els.fillsBody.appendChild(emptyRow(5, "체결 내역 없음"));
    return;
  }
  rows.forEach((fill) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${formatDate(fill.created_at)}</td>
      <td>${escapeHtml(sideLabel(fill.side || "-"))}</td>
      <td>${money(fill.filled_price)}</td>
      <td>${number(fill.filled_amount)}</td>
      <td>${money(fill.fee)}</td>
    `;
    els.fillsBody.appendChild(tr);
  });
}

function renderEvents(events) {
  els.eventsBody.innerHTML = "";
  const rows = events.slice(-18).reverse();
  if (rows.length === 0) {
    els.eventsBody.appendChild(emptyRow(3, "이벤트 없음"));
    return;
  }
  rows.forEach((event) => {
    const detail = summarizeEvent(event);
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${formatDate(event.created_at)}</td>
      <td>${escapeHtml(eventLabel(event.event_type || "-"))}</td>
      <td>${escapeHtml(detail)}</td>
    `;
    els.eventsBody.appendChild(tr);
  });
}

function summarizeEvent(event) {
  const payload = event.payload || {};
  if (event.event_type === "MARKET_TICK") {
    return `${payload.market || ""} 종가 ${number(payload.closing_price)}`;
  }
  if (event.event_type === "ENGINE_STATE") {
    return `${statusLabel(payload.state) || ""} ${payload.reason || ""}`.trim();
  }
  if (event.event_type === "ORDER_REQUEST") {
    return `${sideLabel(payload.type || "")} ${payload.market || ""} ${number(payload.amount)} @ ${number(payload.price)}`;
  }
  if (event.event_type === "ORDER_FILL") {
    return `${sideLabel(payload.side || "")} ${number(payload.filled_amount)} @ ${number(payload.filled_price)}`;
  }
  if (event.event_type === "RISK_REJECT") {
    return `${payload.rule_id || "REJECT"} ${payload.reason || ""}`.trim();
  }
  return payload.reason || payload.status || payload.market || "-";
}

function drawEquityChart(points) {
  drawLineChart({
    canvas: els.chart,
    chartPoints: points
      .map((point) => ({ value: Number(point.asset_value), time: point.record_time }))
      .filter((point) => Number.isFinite(point.value)),
    color: "#147d73",
    markerColor: "#1f8f4d",
    emptyText: "시뮬레이션 데이터를 기다리는 중",
    valueFormatter: money,
    label: "자산",
  });
}

function renderMarketSnapshot(snapshot) {
  const markets = snapshot?.markets || {};
  renderMarket("KRW-BTC", markets["KRW-BTC"], {
    state: els.btcState,
    price: els.btcPrice,
    change: els.btcChange,
    updated: els.btcUpdated,
    chart: els.btcChart,
    color: "#2868b9",
    markerColor: "#1d4f8f",
  });
  renderMarket("KRW-XRP", markets["KRW-XRP"], {
    state: els.xrpState,
    price: els.xrpPrice,
    change: els.xrpChange,
    updated: els.xrpUpdated,
    chart: els.xrpChart,
    color: "#b86f16",
    markerColor: "#8f5510",
  });

  if (snapshot?.error) {
    els.btcState.textContent = "시세 오류";
    els.xrpState.textContent = "시세 오류";
    els.btcState.title = snapshot.error;
    els.xrpState.title = snapshot.error;
  } else if (!snapshot?.running) {
    if (!markets["KRW-BTC"]?.latest) els.btcState.textContent = "시작 대기";
    if (!markets["KRW-XRP"]?.latest) els.xrpState.textContent = "시작 대기";
  }
}

function renderMarket(market, data, targets) {
  const latest = data?.latest;
  const points = data?.points || [];
  targets.state.textContent = latest ? "갱신 중" : "시세 조회 중";
  targets.price.textContent = latest ? money(latest.trade_price) : "-";
  targets.change.textContent = latest ? percent(latest.signed_change_rate) : "-";
  targets.change.className = Number(latest?.signed_change_rate || 0) >= 0 ? "positive" : "negative";
  targets.updated.textContent = latest ? formatTime(latest.date_time) : "-";
  drawLineChart({
    canvas: targets.chart,
    chartPoints: marketChartPoints(points),
    color: targets.color,
    markerColor: targets.markerColor,
    volumeColor: `${targets.color}44`,
    emptyText: `${market} 시세 조회 중`,
    valueFormatter: money,
    volumeFormatter: number,
    label: data?.name || market,
  });
}

function marketChartPoints(points) {
  return points
    .map((point) => ({
      value: Number(point.trade_price),
      time: point.date_time,
      volume: marketPointVolume(point),
    }))
    .filter((point) => Number.isFinite(point.value));
}

function marketPointVolume(point) {
  const tradeVolume = optionalNumber(point.trade_volume);
  if (tradeVolume !== null) return tradeVolume;
  if (point.source === "minute_candle") return optionalNumber(point.acc_trade_volume_24h);
  return null;
}

function drawLineChart({
  canvas,
  chartPoints,
  values,
  color,
  markerColor,
  emptyText,
  valueFormatter = number,
  timeFormatter = formatTime,
  volumeFormatter = number,
  volumeColor = "rgba(20, 125, 115, 0.18)",
  label = "값",
}) {
  const normalizedPoints = chartPoints || (values || []).map((value) => ({ value, time: null }));
  const chartValues = normalizedPoints.map((point) => point.value);
  const chartTimes = normalizedPoints.map((point) => point.time);
  const rect = canvas.getBoundingClientRect();
  const scale = window.devicePixelRatio || 1;
  canvas.width = Math.max(1, Math.floor(rect.width * scale));
  canvas.height = Math.max(1, Math.floor(rect.height * scale));
  const ctx = canvas.getContext("2d");
  ctx.scale(scale, scale);
  const width = rect.width;
  const height = rect.height;
  ctx.clearRect(0, 0, width, height);

  const pad = { top: 20, right: 96, bottom: 38, left: 76 };
  drawGrid(ctx, width, height, pad);

  if (chartValues.length < 2) {
    updateChartHoverState(canvas, null);
    ctx.fillStyle = "#66736f";
    ctx.font = "13px system-ui";
    ctx.fillText(emptyText, 16, 28);
    return;
  }
  const min = Math.min(...chartValues);
  const max = Math.max(...chartValues);
  const span = max - min || 1;
  const plotWidth = Math.max(1, width - pad.left - pad.right);
  const plotHeight = Math.max(1, height - pad.top - pad.bottom);
  updateChartHoverState(canvas, {
    points: normalizedPoints,
    pad,
    plotWidth,
    label,
    valueFormatter,
    timeFormatter,
    volumeFormatter,
  });
  drawVolumeBars({
    ctx,
    points: normalizedPoints,
    pad,
    plotWidth,
    plotHeight,
    volumeColor,
  });
  ctx.beginPath();
  chartValues.forEach((value, index) => {
    const x = pad.left + (index / (chartValues.length - 1)) * plotWidth;
    const y = pad.top + plotHeight - ((value - min) / span) * plotHeight;
    if (index === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.lineWidth = 2.5;
  ctx.strokeStyle = color;
  ctx.stroke();

  drawChartLabels({
    ctx,
    width,
    height,
    pad,
    min,
    max,
    lastValue: chartValues[chartValues.length - 1],
    firstTime: chartTimes[0],
    lastTime: chartTimes[chartTimes.length - 1],
    valueFormatter,
    timeFormatter,
    markerColor,
  });

  const lastY = pad.top + plotHeight - ((chartValues[chartValues.length - 1] - min) / span) * plotHeight;
  const lastX = pad.left + plotWidth;
  ctx.fillStyle = markerColor;
  ctx.beginPath();
  ctx.arc(lastX, lastY, 4, 0, Math.PI * 2);
  ctx.fill();
}

function updateChartHoverState(canvas, config) {
  if (!config) {
    chartHoverState.delete(canvas);
    hideChartTooltip();
    return;
  }
  chartHoverState.set(canvas, config);
  if (canvas.dataset.hoverTooltipReady === "true") return;
  canvas.addEventListener("mousemove", (event) => showChartTooltip(event, canvas));
  canvas.addEventListener("mouseleave", hideChartTooltip);
  canvas.dataset.hoverTooltipReady = "true";
}

function showChartTooltip(event, canvas) {
  const config = chartHoverState.get(canvas);
  if (!config || config.points.length === 0) {
    hideChartTooltip();
    return;
  }
  const rect = canvas.getBoundingClientRect();
  const localX = event.clientX - rect.left;
  const ratio = Math.max(0, Math.min(1, (localX - config.pad.left) / config.plotWidth));
  const index = Math.max(0, Math.min(config.points.length - 1, Math.round(ratio * (config.points.length - 1))));
  const point = config.points[index];
  const valueText = config.valueFormatter(point.value);
  const timeText = point.time ? config.timeFormatter(point.time) : "-";
  const volume = optionalNumber(point.volume);
  const volumeText = volume === null ? "" : `<span>거래량: ${escapeHtml(config.volumeFormatter(volume))}</span>`;
  const tooltip = getChartTooltip();
  tooltip.innerHTML = `<strong>${escapeHtml(config.label)}: ${escapeHtml(valueText)}</strong><span>${escapeHtml(timeText)}</span>${volumeText}`;
  tooltip.style.display = "block";
  positionChartTooltip(event, tooltip);
}

function getChartTooltip() {
  if (!chartTooltip) {
    chartTooltip = document.createElement("div");
    chartTooltip.className = "chart-tooltip";
    chartTooltip.setAttribute("role", "tooltip");
    document.body.appendChild(chartTooltip);
  }
  return chartTooltip;
}

function positionChartTooltip(event, tooltip) {
  const margin = 8;
  const offset = 12;
  let left = event.clientX + offset;
  let top = event.clientY + offset;
  if (left + tooltip.offsetWidth > window.innerWidth - margin) {
    left = event.clientX - tooltip.offsetWidth - offset;
  }
  if (top + tooltip.offsetHeight > window.innerHeight - margin) {
    top = event.clientY - tooltip.offsetHeight - offset;
  }
  tooltip.style.left = `${Math.max(margin, left)}px`;
  tooltip.style.top = `${Math.max(margin, top)}px`;
}

function hideChartTooltip() {
  if (chartTooltip) chartTooltip.style.display = "none";
}

function drawVolumeBars({ ctx, points, pad, plotWidth, plotHeight, volumeColor }) {
  const volumes = points.map((point) => optionalNumber(point.volume));
  const finiteVolumes = volumes.filter((value) => value !== null && value > 0);
  if (finiteVolumes.length === 0) return;

  const maxVolume = Math.max(...finiteVolumes);
  const barAreaHeight = Math.max(26, plotHeight * 0.28);
  const barBottom = pad.top + plotHeight;
  const slotWidth = plotWidth / Math.max(1, points.length - 1);
  const barWidth = Math.max(2, Math.min(12, slotWidth * 0.72));

  ctx.save();
  ctx.fillStyle = volumeColor;
  volumes.forEach((volume, index) => {
    if (volume === null || volume <= 0) return;
    const xCenter = pad.left + (index / Math.max(1, points.length - 1)) * plotWidth;
    const height = Math.max(1, (volume / maxVolume) * barAreaHeight);
    const x = Math.max(pad.left, xCenter - barWidth / 2);
    const y = barBottom - height;
    const width = Math.min(barWidth, pad.left + plotWidth - x);
    ctx.fillRect(x, y, width, height);
  });

  ctx.fillStyle = "#87938f";
  ctx.font = "11px system-ui";
  ctx.textBaseline = "bottom";
  ctx.textAlign = "left";
  ctx.fillText("거래량", pad.left + 4, barBottom - barAreaHeight - 4);
  ctx.restore();
}

function drawChartLabels({
  ctx,
  width,
  height,
  pad,
  min,
  max,
  lastValue,
  firstTime,
  lastTime,
  valueFormatter,
  timeFormatter,
  markerColor,
}) {
  ctx.save();
  ctx.fillStyle = "#66736f";
  ctx.font = "11px system-ui";
  ctx.textAlign = "right";
  ctx.textBaseline = "middle";
  ctx.fillText(valueFormatter(max), pad.left - 8, pad.top + 2);
  ctx.fillText(valueFormatter(min), pad.left - 8, height - pad.bottom);

  ctx.textAlign = "left";
  ctx.textBaseline = "top";
  if (firstTime) ctx.fillText(timeFormatter(firstTime), pad.left, height - pad.bottom + 12);
  if (lastTime) {
    ctx.textAlign = "right";
    ctx.fillText(timeFormatter(lastTime), width - pad.right, height - pad.bottom + 12);
  }

  ctx.textAlign = "left";
  ctx.textBaseline = "middle";
  ctx.fillStyle = markerColor;
  ctx.font = "12px system-ui";
  ctx.fillText(valueFormatter(lastValue), width - pad.right + 10, pad.top + 12);
  if (lastTime) {
    ctx.fillStyle = "#66736f";
    ctx.font = "11px system-ui";
    ctx.fillText(timeFormatter(lastTime), width - pad.right + 10, pad.top + 30);
  }
  ctx.restore();
}

function drawGrid(ctx, width, height, pad = { top: 0, right: 0, bottom: 0, left: 0 }) {
  ctx.strokeStyle = "#e3ebe8";
  ctx.lineWidth = 1;
  const left = pad.left;
  const right = width - pad.right;
  for (let i = 1; i < 4; i += 1) {
    const y = pad.top + ((height - pad.top - pad.bottom) / 4) * i;
    ctx.beginPath();
    ctx.moveTo(left, y);
    ctx.lineTo(right, y);
    ctx.stroke();
  }
}

function emptyRow(colspan, text) {
  const tr = document.createElement("tr");
  const td = document.createElement("td");
  td.colSpan = colspan;
  td.className = "muted";
  td.textContent = text;
  tr.appendChild(td);
  return tr;
}

function setBusy(enabled) {
  state.controlsBusy = enabled;
  updateRunControls();
}

function updateRunControls(snapshot = state.latestSnapshot) {
  const isActive = ACTIVE_RUN_STATES.has(snapshot?.state);
  els.startButton.disabled = state.controlsBusy || isActive;
  els.stopButton.disabled = state.controlsBusy || !isActive;
}

function showError(message) {
  els.serverState.textContent = "오류";
  els.serverState.className = "pill error";
  els.lastTick.textContent = message;
}

function statusLabel(value) {
  return {
    INIT: "초기화",
    READY: "준비",
    RUNNING: "실행 중",
    PAUSED: "일시정지",
    STOPPING: "중지 중",
    STOPPED: "중지됨",
    ERROR: "오류",
  }[value] || "대기";
}

function eventLabel(value) {
  return {
    MARKET_TICK: "시장 데이터",
    SIGNAL: "전략 신호",
    ORDER_REQUEST: "주문 요청",
    ORDER_ACK: "주문 접수",
    ORDER_FILL: "체결",
    ACCOUNT_SNAPSHOT: "계좌 스냅샷",
    RISK_REJECT: "리스크 거절",
    ENGINE_STATE: "엔진 상태",
  }[value] || value;
}

function sideLabel(value) {
  return { buy: "매수", sell: "매도", cancel: "취소", hold: "대기" }[value] || value;
}

function marketLabel(value) {
  return {
    "KRW-BTC": "비트코인",
    "KRW-XRP": "엑스알피(리플)",
  }[value] || value;
}

function money(value) {
  if (value === undefined || value === null || value === "") return "-";
  const amount = Number(value);
  if (!Number.isFinite(amount)) return String(value);
  return amount.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

function number(value) {
  if (value === undefined || value === null || value === "") return "-";
  const amount = Number(value);
  if (!Number.isFinite(amount)) return String(value);
  return amount.toLocaleString(undefined, { maximumFractionDigits: 8 });
}

function optionalNumber(value) {
  if (value === undefined || value === null || value === "") return null;
  const amount = Number(value);
  return Number.isFinite(amount) ? amount : null;
}

function percent(value) {
  if (value === undefined || value === null || value === "") return "-";
  const amount = Number(value);
  if (!Number.isFinite(amount)) return String(value);
  return `${(amount * 100).toFixed(3)}%`;
}

function formatDate(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString();
}

function formatTime(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleTimeString();
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

els.startButton.addEventListener("click", startRun);
els.stopButton.addEventListener("click", stopRun);
els.orderKind.addEventListener("change", updateOrderForm);
els.testOrderButton.addEventListener("click", testManualOrder);
els.submitOrderButton.addEventListener("click", submitManualOrder);
updateOrderForm();
updateRunControls();
window.addEventListener("resize", () => {
  if (!state.latestSnapshot) return;
  drawEquityChart(state.latestSnapshot.equity_points || []);
  renderMarketSnapshot(state.latestMarketSnapshot);
});

loadConfigs()
  .then(() => {
    restoreDashboardState();
    beginAccountPolling();
    return loadLatestRun();
  })
  .catch((error) => showError(error.message));
