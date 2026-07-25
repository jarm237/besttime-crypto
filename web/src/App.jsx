import { useState, useEffect } from 'react';
import axios from 'axios';
import { LineChart, Activity, Briefcase, Plus, X, RefreshCw, Crosshair, TrendingUp, TrendingDown, Bot, Shield, AlertTriangle } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import './index.css';

const API_BASE = 'http://localhost:8000/api';

const isFiniteNumber = (v) => typeof v === 'number' && Number.isFinite(v);

const getMetaState = (signalScore) => {
  const ss = signalScore && typeof signalScore === 'object' ? signalScore : {};
  const error = ss.meta_error;

  let pct = null;
  if (isFiniteNumber(ss.meta_confidence_pct)) {
    pct = Math.round(ss.meta_confidence_pct);
  } else if (isFiniteNumber(ss.meta_confidence)) {
    pct = Math.round(ss.meta_confidence * 100);
  }

  if (pct !== null) {
    const color = pct >= 70 ? '#22c55e' : pct >= 50 ? '#f59e0b' : '#ef4444';
    const label = pct >= 70 ? 'Strong' : pct >= 50 ? 'Medium' : 'Weak';
    return { pct, color, label, status: 'ok' };
  }

  if (error === 'no_model' || (typeof error === 'string' && error.startsWith('no_model'))) {
    return { pct: null, color: '#94a3b8', label: 'No model', status: 'no_model' };
  }
  if (error) {
    return { pct: null, color: '#ef4444', label: 'Meta error', status: 'error' };
  }
  return { pct: null, color: '#64748b', label: 'No data', status: 'no_data' };
};

function App() {
  const [activeTab, setActiveTab] = useState('market');
  const [signals, setSignals] = useState({});
  const [positions, setPositions] = useState([]);
  const [performance, setPerformance] = useState({});
  const [perfAuto, setPerfAuto] = useState({});
  const [perfManual, setPerfManual] = useState({});
  const [perfTab, setPerfTab] = useState('ALL');
  const [availableCoins, setAvailableCoins] = useState(['BTC', 'ETH', 'SOL', 'BNB', 'XRP']);
  const [aiAnalysis, setAiAnalysis] = useState(null);
  const [autoTradeStatus, setAutoTradeStatus] = useState(null);
  const [autoTradeLogs, setAutoTradeLogs] = useState([]);
  const [metaModel, setMetaModel] = useState(null);
  const [loading, setLoading] = useState(true);
  const [showAddModal, setShowAddModal] = useState(false);
  const [showCloseModal, setShowCloseModal] = useState(null);
  const [showDetailModal, setShowDetailModal] = useState(null);

  const [newPos, setNewPos] = useState({ coin: 'BTC', entry_price: '', direction: 'LONG', note: '', invested_usdt: '', manual_decision_basis: 'personal_discretion', signal_id: '' });
  const [closePrice, setClosePrice] = useState('');
  
  const [showPartialModal, setShowPartialModal] = useState(null);
  const [partialPercentage, setPartialPercentage] = useState(50);
  const [partialPrice, setPartialPrice] = useState('');

  const [backtestParams, setBacktestParams] = useState({
    initial_capital: 10000,
    timeframe: '15m',
    coins: ['BTC', 'ETH', 'SOL'],
    latency_ms: 250,
    fee_bps: 5.0,
    slippage_bps: 1.0
  });
  const [activeBacktestTask, setActiveBacktestTask] = useState(null);
  const [backtestHistory, setBacktestHistory] = useState([]);
  const [selectedReport, setSelectedReport] = useState(null);

  const fetchBacktestData = async () => {
    try {
      const [taskRes, historyRes] = await Promise.all([
        axios.get(`${API_BASE}/backtests/active-task`).catch(() => ({ data: null })),
        axios.get(`${API_BASE}/backtests/history`).catch(() => ({ data: [] }))
      ]);
      setActiveBacktestTask(taskRes.data);
      setBacktestHistory(historyRes.data || []);
      
      if (taskRes.data?.run_id && taskRes.data?.status === 'completed' && (!selectedReport || selectedReport.run_id !== taskRes.data.run_id)) {
        const rptRes = await axios.get(`${API_BASE}/backtests/report/${taskRes.data.run_id}`);
        setSelectedReport(rptRes.data);
      }
    } catch (err) {
      console.error('Error fetching backtest data', err);
    }
  };

  const handleRunBacktest = async () => {
    try {
      setSelectedReport(null);
      await axios.post(`${API_BASE}/backtests/run`, backtestParams);
      fetchBacktestData();
    } catch (err) {
      alert(err.response?.data?.detail || 'Error running backtest');
    }
  };

  const handleSelectReport = async (runId) => {
    try {
      const res = await axios.get(`${API_BASE}/backtests/report/${runId}`);
      setSelectedReport(res.data);
    } catch (err) {
      alert(err.response?.data?.detail || 'Error loading report');
    }
  };

  const [executionConfig, setExecutionConfig] = useState(null);
  const [executionFills, setExecutionFills] = useState([]);
  const [executionStats, setExecutionStats] = useState(null);
  const [executionReport, setExecutionReport] = useState(null);

  const [simulatorParams, setSimulatorParams] = useState({
    coin: 'BTC',
    signal_raw: 'BUY (Crossover)',
    close_price: '50000',
    high_price: '50500',
    low_price: '49500',
    volume: '150',
    urgency: 'NORMAL'
  });
  const [simulatorResult, setSimulatorResult] = useState(null);

  const handleSimulateOrder = async () => {
    try {
      setSimulatorResult(null);
      const res = await axios.post(`${API_BASE}/execution/submit`, {
        coin: simulatorParams.coin,
        signal_raw: simulatorParams.signal_raw,
        close_price: parseFloat(simulatorParams.close_price),
        high_price: parseFloat(simulatorParams.high_price),
        low_price: parseFloat(simulatorParams.low_price),
        volume: parseFloat(simulatorParams.volume),
        urgency: simulatorParams.urgency
      });
      setSimulatorResult(res.data);
      fetchExecutionData();
    } catch (err) {
      alert(err.response?.data?.detail || 'Error submitting simulated order');
    }
  };

  const fetchExecutionData = async () => {
    try {
      const [configRes, fillsRes, statsRes, reportRes] = await Promise.all([
        axios.get(`${API_BASE}/execution/config`).catch(() => ({ data: null })),
        axios.get(`${API_BASE}/execution/fills`).catch(() => ({ data: { fills: [] } })),
        axios.get(`${API_BASE}/execution/stats`).catch(() => ({ data: null })),
        axios.get(`${API_BASE}/execution/quality-report`).catch(() => ({ data: null }))
      ]);
      setExecutionConfig(configRes.data);
      setExecutionFills(fillsRes.data?.fills || []);
      setExecutionStats(statsRes.data);
      setExecutionReport(reportRes.data);
    } catch (err) {
      console.error('Error fetching execution data', err);
    }
  };

  const fetchData = async () => {
    setLoading(true);
    try {
      const [sigRes, posRes, perfRes, confRes, aiRes, autoStatusRes, autoLogsRes, metaModelRes] = await Promise.all([
        axios.get(`${API_BASE}/market-signals`).catch(() => ({ data: { signals: {} } })),
        axios.get(`${API_BASE}/positions`).catch(() => ({ data: { positions: [] } })),
        axios.get(`${API_BASE}/performance`).catch(() => ({ data: { performance: {} } })),
        axios.get(`${API_BASE}/config`).catch(() => ({ data: { coins: [] } })),
        axios.get(`${API_BASE}/ai-analysis`).catch(() => ({ data: { report: 'Lỗi tải dữ liệu AI', timestamp: 0 } })),
        axios.get(`${API_BASE}/auto-trade/status`).catch(() => ({ data: null })),
        axios.get(`${API_BASE}/auto-trade/logs`).catch(() => ({ data: [] })),
        axios.get(`${API_BASE}/meta-model`).catch(() => ({ data: null }))
      ]);
      setSignals(sigRes.data.signals || {});
      setPositions(posRes.data.positions || []);
      setPerformance(perfRes.data.performance || {});
      setPerfAuto(perfRes.data.performance_auto || {});
      setPerfManual(perfRes.data.performance_manual || {});
      setAiAnalysis(aiRes.data);
      setAutoTradeStatus(autoStatusRes.data);
      setAutoTradeLogs(autoLogsRes.data || []);
      setMetaModel(metaModelRes.data);
      if (confRes.data.coins && confRes.data.coins.length > 0) {
        setAvailableCoins(confRes.data.coins);
        setNewPos(prev => ({
          ...prev,
          coin: confRes.data.coins.includes(prev.coin) ? prev.coin : confRes.data.coins[0]
        }));
      }
      
      // Fetch backtest data alongside main sync
      fetchBacktestData();
      fetchExecutionData();
    } catch (err) {
      console.error('Error fetching data', err);
    }
    setLoading(false);
  };

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 15000);
    return () => clearInterval(interval);
  }, []);

  const handleAddPosition = async (e) => {
    e.preventDefault();
    try {
      await axios.post(`${API_BASE}/positions`, {
        ...newPos,
        entry_price: parseFloat(newPos.entry_price),
        invested_usdt: parseFloat(newPos.invested_usdt || 0)
      });
      setShowAddModal(false);
      setNewPos({ coin: 'BTC', entry_price: '', direction: 'LONG', note: '', invested_usdt: '', manual_decision_basis: 'personal_discretion', signal_id: '' });
      fetchData();
    } catch (err) {
      alert(err.response?.data?.detail || 'Error adding position');
    }
  };

  const handleClosePosition = async (e) => {
    e.preventDefault();
    try {
      await axios.post(`${API_BASE}/positions/${showCloseModal}/close`, {
        sell_price: parseFloat(closePrice)
      });
      setShowCloseModal(null);
      setClosePrice('');
      fetchData();
    } catch (err) {
      alert(err.response?.data?.detail || 'Error closing position');
    }
  };

  const handlePartialClose = async (e) => {
    e.preventDefault();
    try {
      await axios.post(`${API_BASE}/positions/${showPartialModal}/close-partial`, {
        sell_price: parseFloat(partialPrice),
        percentage: parseFloat(partialPercentage)
      });
      setShowPartialModal(null);
      setPartialPrice('');
      setPartialPercentage(50);
      fetchData();
    } catch (err) {
      alert(err.response?.data?.detail || 'Error closing partial position');
    }
  };

  const renderAutoTrade = () => {
    if (!autoTradeStatus) {
      return <div className="text-secondary text-center py-8">Chưa tải được thông tin AutoTrader hoặc bot chưa khởi động.</div>;
    }

    const isDryRun = autoTradeStatus.mode === 'DRY_RUN';
    const isTripped = autoTradeStatus.circuit_tripped;

    return (
      <div className="flex flex-col gap-6">
        {/* Row 1: Summary Cards */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div className="glass-panel" style={{ marginBottom: 0, padding: '1.25rem' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <h4 style={{ margin: 0, color: 'var(--text-secondary)', fontSize: '0.8rem', textTransform: 'uppercase' }}>Chế độ hoạt động</h4>
                <div style={{ fontSize: '1.8rem', fontWeight: 'bold', marginTop: '0.5rem', color: isDryRun ? '#38bdf8' : '#22c55e' }}>
                  {isDryRun ? 'DRY RUN' : 'LIVE'}
                </div>
              </div>
              <div style={{ width: 44, height: 44, borderRadius: '50%', background: isDryRun ? 'rgba(56,189,248,0.1)' : 'rgba(34,197,94,0.1)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: isDryRun ? '#38bdf8' : '#22c55e' }}>
                <Shield size={24} />
              </div>
            </div>
            <div style={{ color: 'var(--text-secondary)', fontSize: '0.8rem', marginTop: '0.5rem' }}>
              {isDryRun ? 'Chỉ ghi log & gửi cảnh báo, không đặt lệnh thật.' : 'Đặt lệnh Spot thật bằng Binance Testnet Account.'}
            </div>
          </div>

          <div className="glass-panel" style={{ marginBottom: 0, padding: '1.25rem' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <h4 style={{ margin: 0, color: 'var(--text-secondary)', fontSize: '0.8rem', textTransform: 'uppercase' }}>Circuit Breaker</h4>
                <div style={{ fontSize: '1.8rem', fontWeight: 'bold', marginTop: '0.5rem', color: isTripped ? '#ef4444' : '#10b981' }}>
                  {isTripped ? 'TRIPPED (PAUSED)' : 'NORMAL (OK)'}
                </div>
              </div>
              <div style={{ width: 44, height: 44, borderRadius: '50%', background: isTripped ? 'rgba(239,68,68,0.1)' : 'rgba(16,185,129,0.1)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: isTripped ? '#ef4444' : '#10b981' }}>
                <AlertTriangle size={24} />
              </div>
            </div>
            <div style={{ color: 'var(--text-secondary)', fontSize: '0.8rem', marginTop: '0.5rem' }}>
              {isTripped
                ? `Đang tạm dừng 24h do thua ${autoTradeStatus.consecutive_losses} lệnh liên tiếp. Reset sau ${autoTradeStatus.circuit_tripped_remaining_h} giờ.`
                : `Chuỗi thua hiện tại: ${autoTradeStatus.consecutive_losses}/${autoTradeStatus.circuit_breaker_n} lệnh.`
              }
            </div>
          </div>

          <div className="glass-panel" style={{ marginBottom: 0, padding: '1.25rem' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <h4 style={{ margin: 0, color: 'var(--text-secondary)', fontSize: '0.8rem', textTransform: 'uppercase' }}>Tần suất hôm nay</h4>
                <div style={{ fontSize: '1.8rem', fontWeight: 'bold', marginTop: '0.5rem', color: '#f59e0b' }}>
                  {autoTradeStatus.trades_today} / {autoTradeStatus.max_daily_trades}
                </div>
              </div>
              <div style={{ width: 44, height: 44, borderRadius: '50%', background: 'rgba(245,158,11,0.1)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#f59e0b' }}>
                <Activity size={24} />
              </div>
            </div>
            <div style={{ color: 'var(--text-secondary)', fontSize: '0.8rem', marginTop: '0.5rem' }}>
              Số lệnh đặt thành công trong ngày hôm nay. Giới hạn: {autoTradeStatus.max_daily_trades} lệnh/ngày.
            </div>
          </div>
        </div>

        {/* Row 2: Parameters Grid */}
        <div className="glass-panel" style={{ padding: '1.5rem' }}>
          <h3 style={{ fontSize: '1.1rem', fontWeight: 'bold', marginBottom: '1rem', borderBottom: '1px solid rgba(255,255,255,0.06)', paddingBottom: '0.5rem' }}>Cấu hình tham số chiến lược</h3>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div>
              <span style={{ color: 'var(--text-secondary)', fontSize: '0.8rem' }}>Ngưỡng Meta Model:</span>
              <div style={{ fontWeight: 'bold', fontSize: '1.1rem', color: '#a78bfa' }}>≥ {(autoTradeStatus.meta_threshold * 100).toFixed(0)}%</div>
            </div>
            <div>
              <span style={{ color: 'var(--text-secondary)', fontSize: '0.8rem' }}>Ngưỡng Signal Score:</span>
              <div style={{ fontWeight: 'bold', fontSize: '1.1rem', color: '#a78bfa' }}>≥ {autoTradeStatus.score_threshold}</div>
            </div>
            <div>
              <span style={{ color: 'var(--text-secondary)', fontSize: '0.8rem' }}>Mức rủi ro / lệnh:</span>
              <div style={{ fontWeight: 'bold', fontSize: '1.1rem', color: '#f59e0b' }}>{autoTradeStatus.risk_pct}% tài khoản</div>
            </div>
            <div>
              <span style={{ color: 'var(--text-secondary)', fontSize: '0.8rem' }}>Phân bổ tối đa / lệnh:</span>
              <div style={{ fontWeight: 'bold', fontSize: '1.1rem', color: '#10b981' }}>${autoTradeStatus.max_trade_usdt} USDT</div>
            </div>
          </div>
          <div style={{ marginTop: '1rem', fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
            Whitelist Coins: <b style={{ color: 'var(--text-primary)' }}>{autoTradeStatus.allowed_coins && autoTradeStatus.allowed_coins.length > 0 ? autoTradeStatus.allowed_coins.join(', ') : 'Tất cả'}</b>
          </div>
        </div>

        {/* Row 3: Trade Audit Logs */}
        <div className="glass-panel" style={{ padding: '1.5rem' }}>
          <h3 style={{ fontSize: '1.1rem', fontWeight: 'bold', marginBottom: '1rem' }}>Nhật ký lệnh đặt tự động (Audit Log)</h3>
          {autoTradeLogs.length === 0 ? (
            <div className="text-secondary text-center py-6">Chưa ghi nhận lệnh tự động nào.</div>
          ) : (
            <div className="table-container">
              <table>
                <thead>
                  <tr>
                    <th>Thời Gian</th>
                    <th>Coin</th>
                    <th>Hướng</th>
                    <th>Tín Hiệu</th>
                    <th>Độ tin cậy (Meta)</th>
                    <th>Vốn đặt</th>
                    <th>Entry/SL/TP1</th>
                    <th>ID Lệnh</th>
                    <th>Trạng Thái</th>
                    <th>Lý do</th>
                  </tr>
                </thead>
                <tbody>
                  {[...autoTradeLogs].reverse().map((log, i) => {
                    const isSkipped = log.status === 'skipped' || log.status === 'rejected_by_guard';
                    const isError = log.status === 'error';
                    const isSuccess = !isSkipped && !isError;
                    const logMetaPct = isFiniteNumber(log.meta_confidence_pct)
                      ? Math.round(log.meta_confidence_pct)
                      : (isFiniteNumber(log.meta_confidence) ? Math.round(log.meta_confidence * 100) : null);

                    return (
                      <tr key={i} style={{ opacity: isSkipped ? 0.6 : 1 }}>
                        <td className="font-mono text-sm">{log.timestamp_str || new Date(log.timestamp).toLocaleString()}</td>
                        <td className="font-bold">{log.coin}</td>
                        <td>
                          <span className={`badge ${log.direction === 'LONG' ? 'badge-green' : 'badge-red'}`}>
                            {log.direction}
                          </span>
                        </td>
                        <td className="text-sm">{log.signal}</td>
                        <td className="font-mono">
                          {logMetaPct !== null ? `${logMetaPct}%` : 'No data'} (Score: {log.signal_score ?? 'N/A'})
                        </td>
                        <td className="font-mono">${log.usdt_amount ? log.usdt_amount.toFixed(2) : '0.00'}</td>
                        <td className="font-mono text-sm" style={{ whiteSpace: 'nowrap' }}>
                          <span className="text-primary">${log.entry_price?.toFixed(2)}</span> / <span className="text-red">${log.sl_price?.toFixed(2)}</span> / <span className="text-green">${log.tp1_price?.toFixed(2)}</span>
                        </td>
                        <td className="font-mono text-sm" style={{ maxWidth: '120px', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                          {log.order_id || 'N/A'}
                        </td>
                        <td>
                          {isSkipped ? (
                            <span className="badge badge-warning" title={log.reason_skip}>SKIPPED</span>
                          ) : isError ? (
                            <span className="badge badge-red" title={log.error}>ERROR</span>
                          ) : (
                            <span className="badge badge-green">SUCCESS</span>
                          )}
                        </td>
                        <td
                          className="text-sm"
                          title={log.reason_skip || log.error || ''}
                          style={{ maxWidth: '260px', color: isSkipped || isError ? 'var(--text-primary)' : 'var(--text-secondary)' }}
                        >
                          {log.reason_skip || log.error || 'N/A'}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    );
  };

  const renderMetaModel = () => {
    if (!metaModel) {
      return <div className="text-secondary text-center py-8">Chưa tải được thông tin Meta Model.</div>;
    }

    const metrics = metaModel.metrics || {};
    const importance = metaModel.feature_importance || {};
    const buckets = metrics.calibration_buckets || {};
    const mace = isFiniteNumber(metrics?.calibration_info?.selected_error)
      ? `${metrics.calibration_info.selected_error.toFixed(2)}%`
      : 'N/A';
    const winRatePct = (isFiniteNumber(metrics?.n_samples) && metrics.n_samples > 0 && isFiniteNumber(metrics?.label_dist?.WIN))
      ? `${((metrics.label_dist.WIN / metrics.n_samples) * 100).toFixed(1)}%`
      : 'N/A';

    return (
      <div className="flex flex-col gap-6">
        {/* Row 1: Model Info Cards */}
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          <div className="glass-panel" style={{ marginBottom: 0, padding: '1.25rem' }}>
            <h4 style={{ margin: 0, color: 'var(--text-secondary)', fontSize: '0.8rem', textTransform: 'uppercase' }}>Phiên bản Model</h4>
            <div style={{ fontSize: '1.5rem', fontWeight: 'bold', marginTop: '0.5rem', color: '#818cf8' }}>
              {metrics.version || 'N/A'}
            </div>
            <div style={{ color: 'var(--text-secondary)', fontSize: '0.8rem', marginTop: '0.5rem' }}>
              Trạng thái: <span className="badge badge-green" style={{ padding: '0.1rem 0.4rem', fontSize: '0.7rem' }}>CALIBRATED</span>
            </div>
          </div>

          <div className="glass-panel" style={{ marginBottom: 0, padding: '1.25rem' }}>
            <h4 style={{ margin: 0, color: 'var(--text-secondary)', fontSize: '0.8rem', textTransform: 'uppercase' }}>Số mẫu huấn luyện</h4>
            <div style={{ fontSize: '1.5rem', fontWeight: 'bold', marginTop: '0.5rem', color: '#38bdf8' }}>
              {metrics.n_samples || 0} Trades
            </div>
            <div style={{ color: 'var(--text-secondary)', fontSize: '0.8rem', marginTop: '0.5rem' }}>
              Tổng features: {metrics.n_features || 0} fields
            </div>
          </div>

          <div className="glass-panel" style={{ marginBottom: 0, padding: '1.25rem' }}>
            <h4 style={{ margin: 0, color: 'var(--text-secondary)', fontSize: '0.8rem', textTransform: 'uppercase' }}>Tỷ lệ Win/Loss gốc</h4>
            <div style={{ fontSize: '1.5rem', fontWeight: 'bold', marginTop: '0.5rem', color: '#10b981' }}>
              {winRatePct}
            </div>
            <div style={{ color: 'var(--text-secondary)', fontSize: '0.8rem', marginTop: '0.5rem' }}>
              Thắng: {metrics.label_dist?.WIN || 0} | Thua: {metrics.label_dist?.LOSS || 0}
            </div>
          </div>

          <div className="glass-panel" style={{ marginBottom: 0, padding: '1.25rem' }}>
            <h4 style={{ margin: 0, color: 'var(--text-secondary)', fontSize: '0.8rem', textTransform: 'uppercase' }}>Lỗi Calibration (MACE)</h4>
            <div style={{ fontSize: '1.5rem', fontWeight: 'bold', marginTop: '0.5rem', color: '#fb7185' }}>
              {mace}
            </div>
            <div style={{ color: 'var(--text-secondary)', fontSize: '0.8rem', marginTop: '0.5rem' }}>
              Phương pháp: Isotonic Regression
            </div>
          </div>
        </div>

        {/* Row 2: Features Importance & Calibration Buckets */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Feature Importance Panel */}
          <div className="glass-panel" style={{ padding: '1.5rem', marginBottom: 0 }}>
            <h3 style={{ fontSize: '1.1rem', fontWeight: 'bold', marginBottom: '1.25rem', borderBottom: '1px solid rgba(255,255,255,0.06)', paddingBottom: '0.5rem', color: '#818cf8' }}>
              Độ quan trọng của chỉ báo (Feature Importance)
            </h3>
            {Object.keys(importance).length === 0 ? (
              <div className="text-secondary py-4 text-center">Không có dữ liệu feature importance.</div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                {Object.entries(importance).map(([feat, weight]) => (
                  <div key={feat}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.85rem', marginBottom: '0.25rem' }}>
                      <span style={{ fontFamily: 'monospace', color: '#e2e8f0' }}>{feat}</span>
                      <span style={{ fontWeight: 'bold', color: '#818cf8' }}>{(weight * 100).toFixed(2)}%</span>
                    </div>
                    <div style={{ height: '6px', width: '100%', background: 'rgba(255,255,255,0.06)', borderRadius: '999px', overflow: 'hidden' }}>
                      <div style={{ height: '100%', background: 'linear-gradient(90deg, #4f46e5, #818cf8)', width: `${weight * 100}%`, borderRadius: '999px' }}></div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Calibration Buckets Panel */}
          <div className="glass-panel" style={{ padding: '1.5rem', marginBottom: 0 }}>
            <h3 style={{ fontSize: '1.1rem', fontWeight: 'bold', marginBottom: '1.25rem', borderBottom: '1px solid rgba(255,255,255,0.06)', paddingBottom: '0.5rem', color: '#38bdf8' }}>
              Độ sai lệch kiểm định (Probability Calibration Buckets)
            </h3>
            {Object.keys(buckets).length === 0 ? (
              <div className="text-secondary py-4 text-center">Không có dữ liệu calibration.</div>
            ) : (
              <div className="table-container" style={{ margin: 0 }}>
                <table>
                  <thead>
                    <tr>
                      <th>Khoảng Xác Suất</th>
                      <th>Số Mẫu</th>
                      <th>XS Dự Đoán</th>
                      <th>Win Rate Thực Tế</th>
                      <th>Độ Lệch</th>
                      <th>Trạng Thái</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(buckets).map(([bucket, data]) => {
                      const isOk = data.calibrated;
                      const err = data.calibration_error;

                      return (
                        <tr key={bucket}>
                          <td className="font-mono font-bold">{bucket}</td>
                          <td className="font-mono">{data.count}</td>
                          <td className="font-mono">{data.predicted_wr != null ? `${data.predicted_wr.toFixed(1)}%` : 'N/A'}</td>
                          <td className="font-mono" style={{ fontWeight: 'bold', color: '#e2e8f0' }}>
                            {data.actual_wr != null ? `${data.actual_wr.toFixed(1)}%` : 'N/A'}
                          </td>
                          <td className="font-mono" style={{ color: err != null ? (err >= 0 ? '#10b981' : '#ef4444') : '#94a3b8' }}>
                            {err != null ? (err > 0 ? `+${err.toFixed(1)}%` : `${err.toFixed(1)}%`) : 'N/A'}
                          </td>
                          <td>
                            {isOk ? (
                              <span className="badge badge-green" style={{ fontSize: '0.7rem' }}>OK</span>
                            ) : (
                              <span className="badge badge-warning" style={{ fontSize: '0.7rem', background: 'rgba(245,158,11,0.15)', color: '#f59e0b' }}>UNDERESTIMATED</span>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
            <div style={{ marginTop: '1.5rem', padding: '1rem', background: 'rgba(255,255,255,0.02)', borderRadius: '8px', fontSize: '0.8rem', color: 'var(--text-secondary)', lineHeight: 1.5 }}>
              💡 <b>Underestimated (Đánh giá thấp)</b>: Là trạng thái an toàn. Model dự đoán tỷ lệ thắng thấp hơn tỷ lệ thắng thực tế trong lịch sử (Ví dụ: Dự đoán 75% nhưng thực tế thắng 94.8%). Điều này giúp hạn chế vào lệnh sai lầm.
            </div>
          </div>
        </div>
      </div>
    );
  };

  const renderMarketSignals = () => {
    const coinKeys = Object.keys(signals);
    if (coinKeys.length === 0) return <div className="text-secondary text-center py-8">Chưa có dữ liệu. Vui lòng đợi bot quét.</div>;

    return (
      <div className="table-container">
        <table>
          <thead>
            <tr>
              <th>Cặp Giao Dịch</th>
              <th>Tín Hiệu</th>
              <th>Giá Hiện Tại</th>
              <th>RSI</th>
              <th style={{ color: '#f59e0b' }}>📊 Score</th>
              <th>Trend (SMA200)</th>
              <th>Chandelier</th>
              <th style={{ color: '#a78bfa' }}>🤖 Meta</th>
              <th>Hành Động</th>
            </tr>
          </thead>
          <tbody>
            {coinKeys.map(key => {
              const data = signals[key];
              const coin = key.split(':')[0];
              const isBuy = data.signal.includes('BUY');
              const isSell = data.signal.includes('SELL');

              return (
                <tr key={key}>
                  <td className="font-bold">{coin}</td>
                  <td>
                    <span className={`badge ${isBuy ? 'badge-green' : isSell ? 'badge-red' : 'badge-blue'}`}>
                      {data.signal}
                    </span>
                  </td>
                  <td className="font-mono">${data.close?.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 4 })}</td>
                  <td className={`font-mono ${data.rsi < 30 ? 'text-green' : data.rsi > 70 ? 'text-red' : ''}`}>
                    {data.rsi?.toFixed(1)}
                  </td>
                  <td>
                    {(() => {
                      const displayLabel = data.signal_score?.display_label;
                      const displayScore = data.signal_score?.display_score;
                      const conf = data.signal_score?.confidence;
                      // Fallback for old data
                      const sc = data.signal_score?.score;
                      const action = data.signal_score?.action;
                      const isBuyScore = action === 'BUY';
                      const isSellScore = action === 'SELL';
                      const barColor = isBuyScore ? '#22c55e' : isSellScore ? '#ef4444' : '#f59e0b';
                      const textColor = isBuyScore ? '#22c55e' : isSellScore ? '#ef4444' : '#f59e0b';
                      const label = displayLabel ?? (sc != null ? (isBuyScore ? `BUY ${sc}%` : isSellScore ? `SELL ${100 - sc}%` : 'NEUTRAL') : null);
                      const barWidth = displayScore ?? (sc != null ? (isBuyScore ? sc : isSellScore ? 100 - sc : 0) : 0);
                      if (!label) return <span style={{ color: '#475569', fontSize: '0.8rem' }}>N/A</span>;
                      return (
                        <div style={{ minWidth: 90 }}>
                          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.2rem' }}>
                            <span style={{ fontFamily: 'monospace', fontWeight: 700, fontSize: '0.85rem', color: textColor }}>{label}</span>
                            <span style={{ fontSize: '0.65rem', color: '#64748b', marginLeft: '0.3rem' }}>{conf}</span>
                          </div>
                          <div style={{ height: 4, borderRadius: 999, background: 'rgba(255,255,255,0.08)' }}>
                            <div style={{ height: '100%', borderRadius: 999, width: `${barWidth}%`, background: barColor, transition: 'width 0.4s' }} />
                          </div>
                        </div>
                      );
                    })()}
                  </td>
                  <td>
                    {data.trend_context?.above_sma200 ? (
                      <span className="flex items-center gap-1 text-green"><TrendingUp size={16} /> Uptrend</span>
                    ) : (
                      <span className="flex items-center gap-1 text-red"><TrendingDown size={16} /> Downtrend</span>
                    )}
                  </td>
                  <td>
                    <span className={`badge ${data.trend_context?.chandelier === 'BULL' ? 'badge-green' : 'badge-red'}`}>
                      {data.trend_context?.chandelier || 'UNKNOWN'}
                    </span>
                  </td>
                  <td>
                    {(() => {
                      const meta = getMetaState(data.signal_score);
                      if (meta.pct == null) {
                        return <span style={{ color: meta.color, fontSize: '0.75rem', fontWeight: 600 }}>{meta.label}</span>;
                      }
                      const color = meta.color;
                      return (
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                          <div style={{ width: 36, height: 36, borderRadius: '50%', border: `2px solid ${color}`, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '0.75rem', fontWeight: 700, color }}>
                            {meta.pct}%
                          </div>
                          <span style={{ fontSize: '0.72rem', color: '#64748b' }}>{meta.label}</span>
                        </div>
                      );
                    })()}
                  </td>
                  <td>
                    <button
                      className="btn"
                      style={{ padding: '0.25rem 0.75rem', fontSize: '0.75rem', background: 'rgba(255,255,255,0.1)' }}
                      onClick={() => setShowDetailModal(key)}
                    >
                      Chi tiết
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    );
  };

  const renderPositions = () => {
    if (positions.length === 0) return (
      <div className="text-secondary text-center py-8">
        Không có vị thế nào đang mở.
      </div>
    );

    return (
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3">
        {positions.map((pos, idx) => {
          const currentPrice = pos.last_price || pos.entry_price;
          const pnl = pos.direction === 'LONG'
            ? ((currentPrice - pos.entry_price) / pos.entry_price * 100)
            : ((pos.entry_price - currentPrice) / pos.entry_price * 100);

          const isProfitable = pnl >= 0;

          return (
            <div key={idx} className="glass-panel" style={{ marginBottom: 0 }}>
              <div className="flex justify-between items-center mb-4">
                <div className="flex items-center gap-2">
                  <h3 className="font-bold text-xl m-0">{pos.coin}</h3>
                  <span className={`badge ${pos.direction === 'LONG' ? 'badge-green' : 'badge-red'}`}>
                    {pos.direction}
                  </span>
                  {pos.is_auto ? (
                    <span style={{ fontSize: '0.7rem', padding: '0.15rem 0.4rem', borderRadius: '4px', background: 'rgba(167,139,250,0.2)', color: '#a78bfa', fontWeight: 'bold' }}>
                      AUTO
                    </span>
                  ) : (
                    <span style={{ fontSize: '0.7rem', padding: '0.15rem 0.4rem', borderRadius: '4px', background: 'rgba(56,189,248,0.2)', color: '#38bdf8', fontWeight: 'bold' }}>
                      MANUAL
                    </span>
                  )}
                  {!pos.is_auto && pos.manual_decision_basis === 'system_signal' && (
                    <span style={{ fontSize: '0.7rem', padding: '0.15rem 0.4rem', borderRadius: '4px', background: 'rgba(34,197,94,0.2)', color: '#22c55e', fontWeight: 'bold' }}>
                      SYSTEM SIGNAL
                    </span>
                  )}
                  {!pos.is_auto && pos.manual_decision_basis === 'personal_discretion' && (
                    <span style={{ fontSize: '0.7rem', padding: '0.15rem 0.4rem', borderRadius: '4px', background: 'rgba(245,158,11,0.2)', color: '#f59e0b', fontWeight: 'bold' }}>
                      PERSONAL
                    </span>
                  )}
                  {pos.dca_opportunity && (
                    <span style={{ fontSize: '0.7rem', padding: '0.15rem 0.4rem', borderRadius: '4px', background: 'rgba(236,72,153,0.2)', color: '#ec4899', fontWeight: 'bold' }} title="Mô hình xác nhận điều kiện DCA tốt">
                      ➕ DCA
                    </span>
                  )}
                </div>
                <div className={`text-xl font-bold ${isProfitable ? 'text-green' : 'text-red'}`}>
                  {isProfitable ? '+' : ''}{pnl.toFixed(2)}%
                </div>
              </div>

              <div className="text-secondary text-sm mb-4">
                <div className="flex justify-between mb-1">
                  <span>Entry:</span> <span className="text-primary font-mono">${pos.entry_price}</span>
                </div>
                {pos.invested_usdt > 0 && (
                  <div className="flex justify-between mb-1">
                    <span>Vốn:</span> <span className="text-primary font-mono">${pos.invested_usdt}</span>
                  </div>
                )}
                <div className="flex justify-between mb-1">
                  <span>Current:</span> <span className="text-primary font-mono">${currentPrice}</span>
                </div>
                {pos.suggested_sl > 0 && (
                  <div className="flex justify-between mb-1">
                    <span>SL:</span> <span className="text-red font-mono">${pos.suggested_sl}</span>
                  </div>
                )}
                {pos.last_signal && (
                  <div className="flex justify-between mt-2 pt-2 border-t border-gray-700">
                    <span>Signal:</span> <span className="text-primary">{pos.last_signal}</span>
                  </div>
                )}
                {pos.live_meta_confidence !== undefined && pos.live_meta_confidence !== null && (
                  <div className="flex justify-between mt-1 pt-1">
                    <span>XS thắng (Meta):</span>
                    <span style={{
                      fontWeight: 'bold',
                      color: pos.live_meta_confidence >= 0.7 ? '#22c55e' : pos.live_meta_confidence >= 0.5 ? '#f59e0b' : '#ef4444'
                    }}>
                      {(pos.live_meta_confidence * 100).toFixed(0)}%
                    </span>
                  </div>
                )}
                {pos.dca_opportunity && (
                  <div className="mt-2 pt-2 border-t border-dashed border-pink-500/30 text-pink-400">
                    <div className="flex justify-between mb-1">
                      <span>Nên DCA thêm:</span> <span className="font-mono font-bold">${pos.dca_opportunity.suggested_dca_size}</span>
                    </div>
                    <div className="flex justify-between mb-1">
                      <span>Entry sau DCA:</span> <span className="font-mono font-bold">${pos.dca_opportunity.new_avg_entry}</span>
                    </div>
                    <div className="flex justify-between">
                      <span>XS thắng DCA:</span> <span className="font-bold">{(pos.dca_opportunity.sim_meta_prob * 100).toFixed(0)}%</span>
                    </div>
                  </div>
                )}
              </div>

              <div className="flex gap-2 w-full">
                <button
                  onClick={() => setShowPartialModal(pos.coin)}
                  className="btn flex-1"
                  style={{ background: 'rgba(56,189,248,0.1)', color: '#38bdf8', borderColor: 'rgba(56,189,248,0.3)' }}
                >
                  <TrendingDown size={16} /> Chốt 1 phần
                </button>
                <button
                  onClick={() => setShowCloseModal(pos.coin)}
                  className="btn btn-danger flex-1"
                >
                  <X size={16} /> Đóng Vị Thế
                </button>
              </div>
            </div>
          );
        })}
      </div>
    );
  };

  const renderDetailModal = () => {
    if (!showDetailModal || !signals[showDetailModal]) return null;
    const data = signals[showDetailModal];
    const coin = showDetailModal.split(':')[0];
    const isBuy = data.signal.includes('BUY');
    const isSell = data.signal.includes('SELL');

    // Regime
    let regime = 'SIDEWAY'; let regimeTxt = 'Chưa có xu hướng rõ ràng'; let regimeIcon = '↔';
    if (data.trend_context?.above_sma200 && data.trend_context?.chandelier === 'BULL') { regime = 'TĂNG'; regimeTxt = 'Xu hướng tăng rõ ràng'; regimeIcon = '↗'; }
    else if (!data.trend_context?.above_sma200 && data.trend_context?.chandelier === 'BEAR') { regime = 'GIẢM'; regimeTxt = 'Xu hướng giảm rõ ràng'; regimeIcon = '↘'; }

    // Volatility
    const volLow = data.atr < 5; const volHigh = data.atr > 20;
    const volLabel = volHigh ? 'CAO' : volLow ? 'THẤP' : 'TRUNG BÌNH';
    const volDesc = volHigh ? 'Biến động cao' : volLow ? 'Biến động thấp' : 'Biến động vừa';

    // Risk
    const rr = data.tp_sl?.rr2 || data.tp_sl?.rr1 || 0;
    const riskLabel = rr > 2 ? 'THẤP' : rr < 1 ? 'CAO' : 'TRUNG BÌNH';
    const riskDesc = rr > 2 ? 'Quản trị vốn tốt' : rr < 1 ? 'Rủi ro cao' : 'Quản trị vốn chặt chẽ';

    const slDistPct = Math.abs((data.tp_sl?.entry || 0) - (data.tp_sl?.sl || 0)) / (data.tp_sl?.entry || 1);
    const minCapital = slDistPct > 0 ? Math.ceil(Math.max(50, 500 * slDistPct)) : 0;

    const tpDistPct = Math.abs((data.tp_sl?.tp1 || 0) - (data.tp_sl?.entry || 0)) / (data.tp_sl?.entry || 1);
    const netProfitPct = tpDistPct - 0.002; // assume 0.2% round trip fee
    const capitalFor5Net = netProfitPct > 0 ? Math.ceil(5 / netProfitPct) : 0;

    // Confidence score
    let score = 50;
    if (isBuy) { score += data.trend_context?.above_sma200 ? 15 : -10; score += data.trend_context?.chandelier === 'BULL' ? 10 : -10; score += data.rsi < 40 ? 10 : 0; score += data.macd_hist > 0 ? 5 : 0; }
    else if (isSell) { score += !data.trend_context?.above_sma200 ? 15 : -10; score += data.trend_context?.chandelier === 'BEAR' ? 10 : -10; score += data.rsi > 60 ? 10 : 0; score += data.macd_hist < 0 ? 5 : 0; }
    else { score = 68; }
    score = Math.min(Math.max(score, 0), 100);

    // Price slider position %
    const res = data.resistance || data.close * 1.02;
    const sup = data.support || data.close * 0.98;
    const priceRange = res - sup;
    const pricePos = priceRange > 0 ? Math.min(Math.max(((data.close - sup) / priceRange) * 100, 0), 100) : 50;

    const now = new Date();
    const ts = `${now.getHours().toString().padStart(2, '0')}:${now.getMinutes().toString().padStart(2, '0')} ${now.getDate().toString().padStart(2, '0')}/${(now.getMonth() + 1).toString().padStart(2, '0')}/${now.getFullYear()}`;

    const signalColor = isBuy ? '#22c55e' : isSell ? '#ef4444' : '#f59e0b';
    const signalIcon = isBuy ? '▲' : isSell ? '▼' : '⚠';
    const signalBg = isBuy ? 'rgba(34,197,94,0.08)' : isSell ? 'rgba(239,68,68,0.08)' : 'rgba(245,158,11,0.08)';
    const signalBorder = isBuy ? 'rgba(34,197,94,0.25)' : isSell ? 'rgba(239,68,68,0.25)' : 'rgba(245,158,11,0.25)';

    return (
      <div className="modal-overlay" onClick={() => setShowDetailModal(null)}>
        <div onClick={e => e.stopPropagation()} className="modal-content" style={{ maxWidth: '850px', padding: 0 }}>

          {/* ── HEADER ── */}
          <div className="modal-header" style={{ padding: '1.5rem', marginBottom: 0, borderBottom: '1px solid var(--border-color)', background: 'rgba(0,0,0,0.2)', borderTopLeftRadius: '1.5rem', borderTopRightRadius: '1.5rem' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
              <div style={{ width: 40, height: 40, borderRadius: '50%', background: 'linear-gradient(135deg,#f0b90b,#f8d47a)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '1.1rem', fontWeight: 700, color: '#000' }}>
                {coin.slice(0, 2)}
              </div>
              <div>
                <div style={{ fontWeight: 700, fontSize: '1.3rem' }}>{coin}/USDT</div>
                <div style={{ color: '#94a3b8', fontSize: '0.8rem' }}>Chi Tiết Tín Hiệu</div>
              </div>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
              <div style={{ color: 'var(--text-secondary)', fontSize: '0.8rem', display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                <span>🕐</span> Cập nhật: {ts}
              </div>
              <button className="close-btn" onClick={() => setShowDetailModal(null)}>✕</button>
            </div>
          </div>

          <div style={{ padding: '1.5rem', display: 'flex', flexDirection: 'column', gap: '1.25rem', maxHeight: 'calc(90vh - 85px)', overflowY: 'auto' }}>

            {/* ── ROW 1: Signal + Price ── */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>

              {/* Signal block */}
              <div style={{ background: signalBg, border: `1px solid ${signalBorder}`, borderRadius: '0.75rem', padding: '1.25rem' }}>
                <div style={{ fontSize: '0.7rem', color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: '0.75rem' }}>TÍN HIỆU HIỆN TẠI</div>
                <div style={{ display: 'flex', alignItems: 'flex-start', gap: '0.75rem', marginBottom: '0.75rem' }}>
                  <div style={{ width: 44, height: 44, borderRadius: '50%', background: 'rgba(0,0,0,0.3)', border: `2px solid ${signalColor}`, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '1.3rem', color: signalColor, flexShrink: 0 }}>
                    {signalIcon}
                  </div>
                  <div style={{ color: signalColor, fontWeight: 800, fontSize: '1.05rem', lineHeight: 1.3 }}>{data.signal}</div>
                </div>
                <div style={{ color: '#94a3b8', fontSize: '0.8rem', lineHeight: 1.6 }}>{data.reason || 'Phân tích đa chỉ báo'}</div>
                {/* Signal Score bar */}
                {(data.signal_score?.display_label ?? data.signal_score?.score) != null && (
                  <div style={{ marginTop: '0.75rem', paddingTop: '0.75rem', borderTop: '1px solid rgba(255,255,255,0.06)' }}>
                    {(() => {
                      const ss = data.signal_score;
                      const action = ss.action;
                      const scoreColor = action === 'BUY' ? '#22c55e' : action === 'SELL' ? '#ef4444' : '#f59e0b';
                      const barGrad = action === 'BUY' ? 'linear-gradient(to right,#16a34a,#22c55e)' : action === 'SELL' ? 'linear-gradient(to right,#b91c1c,#ef4444)' : 'linear-gradient(to right,#b45309,#f59e0b)';
                      // Use display fields if available, fallback for old data
                      const label = ss.display_label ?? (action === 'BUY' ? `BUY ${ss.score}%` : action === 'SELL' ? `SELL ${100 - ss.score}%` : 'NEUTRAL');
                      const barWidth = ss.display_score ?? (action === 'BUY' ? ss.score : action === 'SELL' ? 100 - ss.score : 0);
                      return (
                        <>
                          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.4rem', fontSize: '0.78rem' }}>
                            <span style={{ color: '#94a3b8' }}>📊 Sức mạnh tín hiệu</span>
                            <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                              <span style={{ fontFamily: 'monospace', fontWeight: 800, fontSize: '1rem', color: scoreColor }}>{label}</span>
                              <span style={{ fontSize: '0.65rem', padding: '0.1rem 0.4rem', borderRadius: 4, background: 'rgba(255,255,255,0.08)', color: '#94a3b8' }}>{ss.confidence}</span>
                              <span style={{ fontSize: '0.65rem', color: '#64748b' }}>size {ss.position_size}</span>
                            </div>
                          </div>
                          <div style={{ height: 6, borderRadius: 999, background: 'rgba(255,255,255,0.06)' }}>
                            <div style={{ height: '100%', borderRadius: 999, width: `${barWidth}%`, background: barGrad, transition: 'width 0.5s' }} />
                          </div>
                          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.65rem', color: '#475569', marginTop: '0.2rem' }}>
                            <span>Yếu</span><span>Vừa</span><span>Mạnh</span>
                          </div>
                        </>
                      );
                    })()}
                  </div>
                )}

                <div style={{ marginTop: '0.75rem', paddingTop: '0.75rem', borderTop: '1px solid rgba(255,255,255,0.06)', display: 'flex', justifyContent: 'space-between', fontSize: '0.8rem' }}>
                  <span style={{ color: '#64748b' }}>CÁC CHỈ BÁO KỸ THUẬT</span>
                  <span style={{ color: data.rsi < 30 ? '#22c55e' : data.rsi > 70 ? '#ef4444' : '#f59e0b', fontWeight: 600 }}>RSI: {data.rsi?.toFixed(1)}</span>
                </div>
              </div>

              {/* Price block */}
              <div style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.08)', borderRadius: '0.75rem', padding: '1.25rem' }}>
                <div style={{ fontSize: '0.7rem', color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: '0.75rem' }}>GIÁ / HỖ TRỢ / KHÁNG CỰ</div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '0.5rem', marginBottom: '1rem', textAlign: 'center' }}>
                  <div>
                    <div style={{ fontSize: '0.7rem', color: '#ef4444', marginBottom: '0.25rem' }}>Kháng cự (Res)</div>
                    <div style={{ fontFamily: 'monospace', fontWeight: 700, color: '#ef4444', fontSize: '1.05rem' }}>${res.toFixed(2)}</div>
                  </div>
                  <div>
                    <div style={{ fontSize: '0.7rem', color: '#94a3b8', marginBottom: '0.25rem' }}>Giá hiện tại</div>
                    <div style={{ fontFamily: 'monospace', fontWeight: 700, color: '#f8fafc', fontSize: '1.05rem' }}>${data.close?.toFixed(2)}</div>
                  </div>
                  <div>
                    <div style={{ fontSize: '0.7rem', color: '#22c55e', marginBottom: '0.25rem' }}>Hỗ trợ (Sup)</div>
                    <div style={{ fontFamily: 'monospace', fontWeight: 700, color: '#22c55e', fontSize: '1.05rem' }}>${sup.toFixed(2)}</div>
                  </div>
                </div>
                {/* Slider */}
                <div style={{ position: 'relative', height: 6, borderRadius: 999, background: 'linear-gradient(to right, #ef4444, #f8fafc 50%, #22c55e)', marginBottom: '0.5rem' }}>
                  <div style={{ position: 'absolute', top: '50%', left: `${100 - pricePos}%`, transform: 'translate(-50%,-50%)', width: 14, height: 14, borderRadius: '50%', background: '#fff', border: '2px solid #1e293b', boxShadow: '0 0 6px rgba(255,255,255,0.6)' }} />
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.7rem', color: '#64748b', fontFamily: 'monospace' }}>
                  <span>{res.toFixed(2)}</span><span>{data.close?.toFixed(2)}</span><span>{sup.toFixed(2)}</span>
                </div>
              </div>
            </div>

            {/* ── ROW 2: Indicators + TP/SL ── */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>

              {/* Indicators */}
              <div style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.08)', borderRadius: '0.75rem', padding: '1.25rem' }}>
                <div style={{ fontSize: '0.7rem', color: '#3b82f6', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: '1rem', display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                  <span>📈</span> CHỈ BÁO KỸ THUẬT
                </div>
                {[
                  ['EMA 9:', data.ema9?.toFixed(2), 'ATR (14):', data.atr?.toFixed(2)],
                  ['EMA 21:', data.ema21?.toFixed(2), 'MACD (12,26,9):', data.macd?.toFixed(2)],
                  ['SMA 50:', data.sma50?.toFixed(2), 'BB Mid (20,2):', data.bb_middle?.toFixed(2)],
                  ['SMA 200:', data.sma200?.toFixed(2) || '0.00', 'RSI (14):', data.rsi?.toFixed(1)],
                ].map(([l1, v1, l2, v2], i) => (
                  <div key={i} style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.5rem', paddingBottom: '0.6rem', marginBottom: '0.6rem', borderBottom: i < 3 ? '1px solid rgba(255,255,255,0.05)' : 'none' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', paddingRight: '0.75rem' }}>
                      <span style={{ color: '#94a3b8', fontSize: '0.85rem' }}>{l1}</span>
                      <span style={{ fontFamily: 'monospace', fontSize: '0.85rem', color: '#a78bfa', fontWeight: 600 }}>{v1}</span>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', paddingLeft: '0.75rem', borderLeft: '1px solid rgba(255,255,255,0.06)' }}>
                      <span style={{ color: '#94a3b8', fontSize: '0.85rem' }}>{l2}</span>
                      <span style={{ fontFamily: 'monospace', fontSize: '0.85rem', color: v2 < 0 ? '#ef4444' : '#a78bfa', fontWeight: 600 }}>{v2}</span>
                    </div>
                  </div>
                ))}
              </div>

              {/* TP/SL Plan */}
              <div style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.08)', borderRadius: '0.75rem', padding: '1.25rem' }}>
                <div style={{ fontSize: '0.7rem', color: '#22c55e', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: '1rem', display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                  <span>🎯</span> KẾ HOẠCH KHUYẾN NGHỊ (TP/SL)
                </div>
                {[
                  ['Mức vào lệnh (Entry):', data.tp_sl?.entry?.toFixed(2), '#f8fafc', true],
                  ['Cắt lỗ (Stop Loss):', data.tp_sl?.sl?.toFixed(2), '#ef4444', true],
                  ['Chốt lời 1 (TP1):', data.tp_sl?.tp1?.toFixed(2), '#22c55e', true],
                  ['Chốt lời 2 (TP2):', data.tp_sl?.tp2?.toFixed(2), '#22c55e', true],
                  ['Vốn tài khoản (Rủi ro 2%):', minCapital > 0 ? minCapital.toString() : 'Tuỳ chọn', '#e2e8f0', minCapital > 0],
                  ['Vốn vào lệnh (Lãi ≥ $5):', capitalFor5Net > 0 ? capitalFor5Net.toString() : 'N/A', '#e2e8f0', capitalFor5Net > 0],
                  ['Phương pháp:', data.tp_sl?.method || 'ATR-Based', '#94a3b8', false],
                ].map(([label, val, color, isDollar], i) => (
                  <div key={i} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', paddingBottom: '0.65rem', marginBottom: '0.65rem', borderBottom: i < 6 ? '1px solid rgba(255,255,255,0.05)' : 'none' }}>
                    <span style={{ color: '#94a3b8', fontSize: '0.85rem' }}>{label}</span>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
                      <span style={{ fontFamily: 'monospace', fontWeight: 600, color, fontSize: '0.9rem' }}>{isDollar && val ? `$${val}` : val}</span>
                      {i === 2 && data.tp_sl?.rr1 && <span style={{ color: '#64748b', fontSize: '0.75rem' }}>(RR: {data.tp_sl.rr1}R)</span>}
                      {i === 3 && data.tp_sl?.rr2 && <span style={{ color: '#64748b', fontSize: '0.75rem' }}>(RR: {data.tp_sl.rr2}R)</span>}
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* ── ROW 3: 4 bottom stat cards ── */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: '0.75rem' }}>
              {[
                { icon: '↔', color: '#a78bfa', label: 'XU HƯỚNG', value: regime, desc: regimeTxt },
                { icon: '📈', color: '#f59e0b', label: 'ĐỘ BIẾN ĐỘNG', value: volLabel, desc: `ATR: ${data.atr?.toFixed(2)}\n${volDesc}` },
                { icon: '📊', color: '#3b82f6', label: 'KHUNG THỜI GIAN', value: '4H', desc: 'Phân tích theo khung 4 giờ' },
                { icon: '🛡', color: '#22c55e', label: 'RỦI RO', value: riskLabel, desc: riskDesc },
              ].map((card, i) => (
                <div key={i} style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.08)', borderRadius: '0.75rem', padding: '1rem' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.5rem' }}>
                    <div style={{ width: 32, height: 32, borderRadius: '50%', background: `rgba(${i === 0 ? '167,139,250' : i === 1 ? '245,158,11' : i === 2 ? '59,130,246' : '34,197,94'},0.15)`, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '0.9rem' }}>{card.icon}</div>
                    <div style={{ fontSize: '0.65rem', color: card.color, textTransform: 'uppercase', letterSpacing: '0.06em', fontWeight: 600 }}>{card.label}</div>
                  </div>
                  <div style={{ fontWeight: 700, fontSize: '1.1rem', color: '#f8fafc', marginBottom: '0.25rem' }}>{card.value}</div>
                  <div style={{ color: '#64748b', fontSize: '0.75rem', lineHeight: 1.4, whiteSpace: 'pre-line' }}>{card.desc}</div>
                </div>
              ))}
            </div>

            {/* ── ROW 4: Meta Model Panel ── */}
            {(() => {
              const meta = getMetaState(data.signal_score);
              const metaPct = meta.pct;
              const metaErr = data.signal_score?.meta_error;
              if (metaPct == null && !metaErr) return null;
              const metaColor = metaPct >= 70 ? '#22c55e' : metaPct >= 50 ? '#f59e0b' : '#ef4444';
              const metaLabel = metaPct >= 70 ? 'Xác suất cao — Tín hiệu đáng tin' : metaPct >= 50 ? 'Xác suất trung bình — Thận trọng' : 'Xác suất thấp — Nên bỏ qua';
              const metaBg = metaPct >= 70 ? 'rgba(34,197,94,0.06)' : metaPct >= 50 ? 'rgba(245,158,11,0.06)' : 'rgba(239,68,68,0.06)';
              const metaBorder = metaPct >= 70 ? 'rgba(34,197,94,0.2)' : metaPct >= 50 ? 'rgba(245,158,11,0.2)' : 'rgba(239,68,68,0.2)';
              return (
                <div style={{ background: metaBg, border: `1px solid ${metaBorder}`, borderRadius: '0.75rem', padding: '1.25rem' }}>
                  <div style={{ fontSize: '0.7rem', color: '#a78bfa', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: '1rem', display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                    <span>🤖</span> META MODEL CONFIDENCE (RandomForest)
                  </div>
                  {metaPct != null ? (
                    <div style={{ display: 'flex', alignItems: 'center', gap: '1.5rem' }}>
                      {/* Circular gauge */}
                      <div style={{ position: 'relative', width: 80, height: 80, flexShrink: 0 }}>
                        <svg viewBox="0 0 80 80" style={{ width: '100%', height: '100%', transform: 'rotate(-90deg)' }}>
                          <circle cx="40" cy="40" r="34" fill="none" stroke="rgba(255,255,255,0.08)" strokeWidth="8" />
                          <circle cx="40" cy="40" r="34" fill="none" stroke={metaColor} strokeWidth="8"
                            strokeDasharray={`${2 * Math.PI * 34 * metaPct / 100} ${2 * Math.PI * 34 * (1 - metaPct / 100)}`}
                            strokeLinecap="round"
                          />
                        </svg>
                        <div style={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center' }}>
                          <div style={{ fontSize: '1.2rem', fontWeight: 800, color: metaColor }}>{metaPct}%</div>
                        </div>
                      </div>
                      <div style={{ flex: 1 }}>
                        <div style={{ fontWeight: 700, color: metaColor, fontSize: '1rem', marginBottom: '0.35rem' }}>{metaLabel}</div>
                        <div style={{ color: '#64748b', fontSize: '0.78rem', lineHeight: 1.5 }}>
                          Xác suất thắng dự đoán từ lịch sử giao dịch.
                          Giai đoạn hiện tại: <b style={{ color: '#a78bfa' }}>Shadow Mode</b> — chỉ hiển thị, chưa can thiệp.
                        </div>
                        {/* Progress bar */}
                        <div style={{ marginTop: '0.75rem', height: 6, borderRadius: 999, background: 'rgba(255,255,255,0.06)' }}>
                          <div style={{ height: '100%', borderRadius: 999, background: `linear-gradient(to right, #ef4444, #f59e0b 50%, #22c55e)`, width: `${metaPct}%`, transition: 'width 0.5s' }} />
                        </div>
                        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.65rem', color: '#475569', marginTop: '0.2rem' }}>
                          <span>0%</span><span>50%</span><span>100%</span>
                        </div>
                      </div>
                    </div>
                  ) : (
                    <div style={{ color: '#64748b', fontSize: '0.85rem' }}>
                      ⚠️ {metaErr === 'no_model' ? 'Model chưa được train. Chạy: python -m btc_scraper.meta_model --train' : `Lỗi: ${metaErr}`}
                    </div>
                  )}
                </div>
              );
            })()}

            {/* Footer */}
            <div style={{ background: 'rgba(59,130,246,0.06)', border: '1px solid rgba(59,130,246,0.15)', borderRadius: '0.5rem', padding: '0.65rem 1rem', fontSize: '0.78rem', color: '#64748b', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <span>ℹ️</span> Lưu ý: Tín hiệu mang tính chất tham khảo. Quản trị rủi ro và kỷ luật là yếu tố quan trọng.
            </div>

          </div>
        </div>
      </div>
    );
  };

  const renderBacktesting = () => {
    return (
      <div className="flex flex-col gap-6">
        {/* Row 1: Configurations & Launch */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="glass-panel lg:col-span-1" style={{ padding: '1.5rem', marginBottom: 0 }}>
            <h3 style={{ fontSize: '1.1rem', fontWeight: 'bold', marginBottom: '1.25rem', borderBottom: '1px solid rgba(255,255,255,0.06)', paddingBottom: '0.5rem' }}>Cấu hình Backtest</h3>
            
            <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
              <div>
                <label className="form-label" style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Số vốn ban đầu (USDT)</label>
                <input
                  type="number"
                  className="form-control"
                  style={{ background: 'rgba(0,0,0,0.3)', border: '1px solid var(--border-color)', borderRadius: '0.375rem', color: '#fff', padding: '0.5rem', width: '100%', marginTop: '0.25rem' }}
                  value={backtestParams.initial_capital}
                  onChange={(e) => setBacktestParams({...backtestParams, initial_capital: parseFloat(e.target.value)})}
                />
              </div>

              <div>
                <label className="form-label" style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Khung thời gian</label>
                <select
                  className="form-control"
                  style={{ background: 'rgba(0,0,0,0.3)', border: '1px solid var(--border-color)', borderRadius: '0.375rem', color: '#fff', padding: '0.5rem', width: '100%', marginTop: '0.25rem' }}
                  value={backtestParams.timeframe}
                  onChange={(e) => setBacktestParams({...backtestParams, timeframe: e.target.value})}
                >
                  <option value="15m">15m</option>
                  <option value="1h">1h</option>
                  <option value="4h">4h</option>
                  <option value="1d">1d</option>
                </select>
              </div>

              <div>
                <label className="form-label" style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Độ trễ Latency (ms)</label>
                <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', marginTop: '0.25rem' }}>
                  <input
                    type="range"
                    min="0"
                    max="3000"
                    step="50"
                    style={{ flex: 1 }}
                    value={backtestParams.latency_ms}
                    onChange={(e) => setBacktestParams({...backtestParams, latency_ms: parseInt(e.target.value)})}
                  />
                  <span style={{ fontFamily: 'monospace', fontWeight: 'bold', width: '50px' }}>{backtestParams.latency_ms}ms</span>
                </div>
              </div>

              <div>
                <label className="form-label" style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Phí giao dịch Futures Taker (bps)</label>
                <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', marginTop: '0.25rem' }}>
                  <input
                    type="range"
                    min="1"
                    max="20"
                    step="0.5"
                    style={{ flex: 1 }}
                    value={backtestParams.fee_bps}
                    onChange={(e) => setBacktestParams({...backtestParams, fee_bps: parseFloat(e.target.value)})}
                  />
                  <span style={{ fontFamily: 'monospace', fontWeight: 'bold', width: '50px' }}>{backtestParams.fee_bps} bps</span>
                </div>
              </div>

              <div>
                <label className="form-label" style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Slippage cơ bản (bps)</label>
                <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', marginTop: '0.25rem' }}>
                  <input
                    type="range"
                    min="0"
                    max="10"
                    step="0.5"
                    style={{ flex: 1 }}
                    value={backtestParams.slippage_bps}
                    onChange={(e) => setBacktestParams({...backtestParams, slippage_bps: parseFloat(e.target.value)})}
                  />
                  <span style={{ fontFamily: 'monospace', fontWeight: 'bold', width: '50px' }}>{backtestParams.slippage_bps} bps</span>
                </div>
              </div>

              <div>
                <label className="form-label" style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '0.5rem', display: 'block' }}>Coin Whitelist</label>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '0.5rem', maxHeight: '120px', overflowY: 'auto', background: 'rgba(0,0,0,0.2)', padding: '0.5rem', borderRadius: '0.25rem' }}>
                  {availableCoins.map(coin => {
                    const isChecked = backtestParams.coins.includes(coin);
                    return (
                      <label key={coin} style={{ display: 'flex', alignItems: 'center', gap: '0.25rem', cursor: 'pointer', fontSize: '0.8rem' }}>
                        <input
                          type="checkbox"
                          checked={isChecked}
                          onChange={() => {
                            const newCoins = isChecked
                              ? backtestParams.coins.filter(c => c !== coin)
                              : [...backtestParams.coins, coin];
                            setBacktestParams({...backtestParams, coins: newCoins});
                          }}
                        />
                        {coin}
                      </label>
                    );
                  })}
                </div>
              </div>

              <button
                className="btn btn-primary w-full mt-4"
                style={{ background: 'linear-gradient(to right, #6366f1, #3b82f6)', fontWeight: 'bold' }}
                disabled={activeBacktestTask?.status === 'running'}
                onClick={handleRunBacktest}
              >
                {activeBacktestTask?.status === 'running' ? 'Đang chạy backtest...' : '🚀 Khởi Chạy Backtest'}
              </button>
            </div>
          </div>

          <div className="glass-panel lg:col-span-2" style={{ padding: '1.5rem', marginBottom: 0 }}>
            {activeBacktestTask?.status === 'running' ? (
              <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100%', padding: '4rem 0' }}>
                <RefreshCw className="animate-spin text-accent mb-4" size={48} />
                <h4 style={{ fontSize: '1.2rem', fontWeight: 'bold', marginBottom: '0.5rem' }}>Đang thực thi tác vụ backtesting chuyên nghiệp...</h4>
                <p style={{ color: 'var(--text-secondary)', fontSize: '0.85rem', marginBottom: '1.5rem' }}>Hệ thống đang mô phỏng khớp lệnh, phí, slippage và tính Monte Carlo 10,000 paths.</p>
                <div style={{ width: '80%', height: '8px', background: 'rgba(255,255,255,0.06)', borderRadius: '999px', overflow: 'hidden' }}>
                  <div style={{ height: '100%', background: 'linear-gradient(to right, var(--accent), var(--green))', width: `${activeBacktestTask.progress}%`, transition: 'width 0.4s' }} />
                </div>
                <span style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginTop: '0.5rem', fontFamily: 'monospace' }}>Tiến độ: {activeBacktestTask.progress}%</span>
              </div>
            ) : selectedReport ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
                {/* Header */}
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid rgba(255,255,255,0.06)', paddingBottom: '0.75rem' }}>
                  <div>
                    <h3 style={{ fontSize: '1.2rem', fontWeight: 'bold', margin: 0 }}>Kết Quả Backtest: Run #{selectedReport.run_id}</h3>
                    <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>Mô phỏng ngày: {new Date(selectedReport.timestamp).toLocaleString()}</span>
                  </div>
                  <div>
                    <span className={`badge ${selectedReport.approval_status?.passed ? 'badge-green' : 'badge-red'}`} style={{ fontSize: '1rem', padding: '0.5rem 1rem' }}>
                      {selectedReport.approval_status?.passed ? 'APPROVED ✅' : 'REJECTED ❌'}
                    </span>
                  </div>
                </div>

                {/* Grid stats */}
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                  <div style={{ background: 'rgba(255,255,255,0.02)', padding: '0.75rem', borderRadius: '0.5rem', border: '1px solid rgba(255,255,255,0.04)' }}>
                    <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>Tổng PnL Net</div>
                    <div style={{ fontSize: '1.4rem', fontWeight: 'bold', color: selectedReport.metrics?.net_pnl >= 0 ? 'var(--green)' : 'var(--red)', marginTop: '0.25rem' }}>
                      {selectedReport.metrics?.total_return >= 0 ? '+' : ''}{(selectedReport.metrics?.total_return * 100).toFixed(2)}%
                    </div>
                  </div>
                  <div style={{ background: 'rgba(255,255,255,0.02)', padding: '0.75rem', borderRadius: '0.5rem', border: '1px solid rgba(255,255,255,0.04)' }}>
                    <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>Sharpe Ratio</div>
                    <div style={{ fontSize: '1.4rem', fontWeight: 'bold', color: 'var(--accent)', marginTop: '0.25rem' }}>
                      {selectedReport.metrics?.sharpe?.toFixed(2)}
                    </div>
                  </div>
                  <div style={{ background: 'rgba(255,255,255,0.02)', padding: '0.75rem', borderRadius: '0.5rem', border: '1px solid rgba(255,255,255,0.04)' }}>
                    <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>Max Drawdown</div>
                    <div style={{ fontSize: '1.4rem', fontWeight: 'bold', color: 'var(--red)', marginTop: '0.25rem' }}>
                      -{(selectedReport.metrics?.max_drawdown * 100).toFixed(2)}%
                    </div>
                  </div>
                  <div style={{ background: 'rgba(255,255,255,0.02)', padding: '0.75rem', borderRadius: '0.5rem', border: '1px solid rgba(255,255,255,0.04)' }}>
                    <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>Cost Drag PnL</div>
                    <div style={{ fontSize: '1.4rem', fontWeight: 'bold', color: 'var(--warning)', marginTop: '0.25rem' }}>
                      {(selectedReport.metrics?.cost_drag * 100).toFixed(1)}%
                    </div>
                  </div>
                </div>

                {/* Gate checks details */}
                <div>
                  <h4 style={{ fontSize: '0.95rem', fontWeight: 'bold', marginBottom: '0.75rem' }}>Strategy Approval Gate Checklist</h4>
                  <div style={{ maxHeight: '180px', overflowY: 'auto', background: 'rgba(0,0,0,0.2)', padding: '0.5rem', borderRadius: '0.375rem', border: '1px solid rgba(255,255,255,0.04)' }}>
                    <table style={{ width: '100%', fontSize: '0.8rem' }}>
                      <thead>
                        <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.06)', color: 'var(--text-secondary)' }}>
                          <th style={{ textAlign: 'left', padding: '0.25rem' }}>Quy tắc</th>
                          <th style={{ textAlign: 'center', padding: '0.25rem' }}>Giá trị đạt</th>
                          <th style={{ textAlign: 'center', padding: '0.25rem' }}>Ngưỡng yêu cầu</th>
                          <th style={{ textAlign: 'right', padding: '0.25rem' }}>Trạng thái</th>
                        </tr>
                      </thead>
                      <tbody>
                        {selectedReport.approval_status?.rules && Object.entries(selectedReport.approval_status.rules).map(([ruleKey, ruleInfo]) => {
                          const isPct = ['max_drawdown', 'cost_drag', 'mc_prob_loss', 'mc_prob_dd_10pct'].includes(ruleKey);
                          const valStr = isPct ? `${(ruleInfo.val * 100).toFixed(1)}%` : ruleInfo.val?.toFixed(2);
                          return (
                            <tr key={ruleKey} style={{ borderBottom: '1px solid rgba(255,255,255,0.03)' }}>
                              <td style={{ padding: '0.4rem 0.25rem', textTransform: 'capitalize' }}>{ruleKey.replace(/_/g, ' ')}</td>
                              <td style={{ textAlign: 'center', fontFamily: 'monospace' }}>{valStr}</td>
                              <td style={{ textAlign: 'center', fontFamily: 'monospace', color: 'var(--text-secondary)' }}>{ruleInfo.target}</td>
                              <td style={{ textAlign: 'right', fontWeight: 'bold', color: ruleInfo.ok ? 'var(--green)' : 'var(--red)' }}>
                                {ruleInfo.ok ? '✅ PASS' : '❌ FAIL'}
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                </div>

                {/* Sub-tabs / Details */}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                  {/* Monte Carlo */}
                  <div style={{ background: 'rgba(255,255,255,0.02)', padding: '1rem', borderRadius: '0.5rem', border: '1px solid rgba(255,255,255,0.04)' }}>
                    <h4 style={{ fontSize: '0.9rem', fontWeight: 'bold', marginBottom: '0.75rem', color: '#a78bfa' }}>Monte Carlo Robustness (10k paths)</h4>
                    <table style={{ width: '100%', fontSize: '0.8rem' }}>
                      <tbody>
                        <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
                          <td style={{ padding: '0.25rem 0', color: 'var(--text-secondary)' }}>Path 5th Percentile Return</td>
                          <td style={{ textAlign: 'right', fontFamily: 'monospace' }}>{(selectedReport.monte_carlo_metrics?.p05_return * 100).toFixed(1)}%</td>
                        </tr>
                        <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
                          <td style={{ padding: '0.25rem 0', color: 'var(--text-secondary)' }}>Path 50th Percentile Return</td>
                          <td style={{ textAlign: 'right', fontFamily: 'monospace' }}>{(selectedReport.monte_carlo_metrics?.p50_return * 100).toFixed(1)}%</td>
                        </tr>
                        <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
                          <td style={{ padding: '0.25rem 0', color: 'var(--text-secondary)' }}>Path 95th Percentile Return</td>
                          <td style={{ textAlign: 'right', fontFamily: 'monospace' }}>{(selectedReport.monte_carlo_metrics?.p95_return * 100).toFixed(1)}%</td>
                        </tr>
                        <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
                          <td style={{ padding: '0.25rem 0', color: 'var(--text-secondary)' }}>Xác suất thua lỗ (Path Loss)</td>
                          <td style={{ textAlign: 'right', fontFamily: 'monospace', color: selectedReport.monte_carlo_metrics?.probability_of_loss > 0.25 ? 'var(--red)' : 'var(--green)' }}>
                            {(selectedReport.monte_carlo_metrics?.probability_of_loss * 100).toFixed(1)}%
                          </td>
                        </tr>
                        <tr>
                          <td style={{ padding: '0.25rem 0', color: 'var(--text-secondary)' }}>Khả năng cháy tài khoản (Risk of Ruin)</td>
                          <td style={{ textAlign: 'right', fontFamily: 'monospace', color: selectedReport.monte_carlo_metrics?.risk_of_ruin > 0.1 ? 'var(--red)' : 'var(--green)' }}>
                            {(selectedReport.monte_carlo_metrics?.risk_of_ruin * 100).toFixed(1)}%
                          </td>
                        </tr>
                      </tbody>
                    </table>
                  </div>

                  {/* Stress tests */}
                  <div style={{ background: 'rgba(255,255,255,0.02)', padding: '1rem', borderRadius: '0.5rem', border: '1px solid rgba(255,255,255,0.04)' }}>
                    <h4 style={{ fontSize: '0.9rem', fontWeight: 'bold', marginBottom: '0.75rem', color: '#3b82f6' }}>Stress Tests & Crashes</h4>
                    <table style={{ width: '100%', fontSize: '0.75rem' }}>
                      <thead>
                        <tr style={{ color: 'var(--text-secondary)', borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
                          <th>Sự kiện</th>
                          <th style={{ textAlign: 'center' }}>N.Trades</th>
                          <th style={{ textAlign: 'right' }}>PnL</th>
                          <th style={{ textAlign: 'right' }}>Max DD</th>
                        </tr>
                      </thead>
                      <tbody>
                        {selectedReport.stress_metrics?.historical && Object.entries(selectedReport.stress_metrics.historical).map(([evtName, evtStats]) => (
                          <tr key={evtName} style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
                            <td style={{ padding: '0.3rem 0' }}>{evtName.replace(/_/g, ' ')}</td>
                            <td style={{ textAlign: 'center', fontFamily: 'monospace' }}>{evtStats.n_trades ?? 0}</td>
                            <td style={{ textAlign: 'right', fontFamily: 'monospace', color: evtStats.total_return >= 0 ? 'var(--green)' : 'var(--red)' }}>
                              {evtStats.total_return != null ? `${(evtStats.total_return * 100).toFixed(1)}%` : 'N/A'}
                            </td>
                            <td style={{ textAlign: 'right', fontFamily: 'monospace', color: 'var(--red)' }}>
                              {evtStats.max_drawdown != null ? `-${(evtStats.max_drawdown * 100).toFixed(1)}%` : 'N/A'}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
                
                {/* Regime split performance */}
                <div>
                  <h4 style={{ fontSize: '0.95rem', fontWeight: 'bold', marginBottom: '0.5rem' }}>Hiệu suất theo Market Regimes</h4>
                  <div className="table-container">
                    <table style={{ width: '100%', fontSize: '0.8rem' }}>
                      <thead>
                        <tr style={{ color: 'var(--text-secondary)', borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
                          <th style={{ textAlign: 'left' }}>Regime</th>
                          <th style={{ textAlign: 'center' }}>Số Trade</th>
                          <th style={{ textAlign: 'center' }}>Win Rate</th>
                          <th style={{ textAlign: 'right' }}>Tổng Return (USDT)</th>
                          <th style={{ textAlign: 'right' }}>Profit Factor</th>
                        </tr>
                      </thead>
                      <tbody>
                        {selectedReport.regime_metrics && Object.entries(selectedReport.regime_metrics).map(([regName, regStats]) => (
                          <tr key={regName} style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
                            <td style={{ padding: '0.4rem 0', fontWeight: 'bold' }}>{regName}</td>
                            <td style={{ textAlign: 'center', fontFamily: 'monospace' }}>{regStats.n_trades}</td>
                            <td style={{ textAlign: 'center', fontFamily: 'monospace' }}>{(regStats.win_rate * 100).toFixed(1)}%</td>
                            <td style={{ textAlign: 'right', fontFamily: 'monospace', color: regStats.total_return >= 0 ? 'var(--green)' : 'var(--red)' }}>
                              ${regStats.total_return.toFixed(2)}
                            </td>
                            <td style={{ textAlign: 'right', fontFamily: 'monospace' }}>{regStats.profit_factor === Infinity ? '∞' : regStats.profit_factor.toFixed(2)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              </div>
            ) : (
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: 'var(--text-secondary)', padding: '8rem 0' }}>
                Chọn một báo cáo backtest trong lịch sử hoặc chạy backtest mới để xem kết quả chi tiết.
              </div>
            )}
          </div>
        </div>

        {/* Row 2: History Runs */}
        <div className="glass-panel" style={{ padding: '1.5rem' }}>
          <h3 style={{ fontSize: '1.1rem', fontWeight: 'bold', marginBottom: '1rem' }}>Lịch sử các lần chạy Backtest</h3>
          {backtestHistory.length === 0 ? (
            <div className="text-secondary text-center py-6">Chưa chạy lần backtest nào.</div>
          ) : (
            <div className="table-container">
              <table>
                <thead>
                  <tr>
                    <th>Run ID</th>
                    <th>Thời Gian</th>
                    <th>Coins whitelist</th>
                    <th>Trades</th>
                    <th>Tổng Net PnL</th>
                    <th>Max Drawdown</th>
                    <th>Sharpe</th>
                    <th>Cổng Phê Duyệt</th>
                    <th>Hành Động</th>
                  </tr>
                </thead>
                <tbody>
                  {backtestHistory.map((run) => (
                    <tr key={run.run_id} style={{ cursor: 'pointer' }} onClick={() => handleSelectReport(run.run_id)}>
                      <td className="font-mono text-sm font-bold text-primary">#{run.run_id}</td>
                      <td>{new Date(run.timestamp).toLocaleString()}</td>
                      <td className="text-sm">{run.coins.join(', ')}</td>
                      <td className="font-mono">{run.n_trades}</td>
                      <td className={`font-mono font-bold ${run.total_return >= 0 ? 'text-green' : 'text-red'}`}>
                        {run.total_return >= 0 ? '+' : ''}{(run.total_return * 100).toFixed(2)}%
                      </td>
                      <td className="font-mono text-red">-{(run.max_drawdown * 100).toFixed(2)}%</td>
                      <td className="font-mono">{run.sharpe.toFixed(2)}</td>
                      <td>
                        <span className={`badge ${run.passed ? 'badge-green' : 'badge-red'}`}>
                          {run.passed ? 'PASSED' : 'REJECTED'}
                        </span>
                      </td>
                      <td>
                        <button className="btn" style={{ fontSize: '0.75rem', padding: '0.2rem 0.5rem', background: 'rgba(255,255,255,0.06)' }} onClick={(e) => { e.stopPropagation(); handleSelectReport(run.run_id); }}>
                          Xem chi tiết
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    );
  };

  const renderExecution = () => {
    return (
      <div className="flex flex-col gap-6">
        {/* Row 1: Key Metrics */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div style={{ background: 'rgba(255,255,255,0.02)', padding: '1rem', borderRadius: '0.75rem', border: '1px solid rgba(255,255,255,0.06)' }}>
            <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Khớp lệnh / Bị từ chối</div>
            <div style={{ fontSize: '1.6rem', fontWeight: 800, marginTop: '0.25rem', color: '#f8fafc' }}>
              {executionStats?.n_fills ?? 0} <span style={{ fontSize: '0.9rem', color: 'var(--text-secondary)', fontWeight: 'normal' }}>/ {executionStats?.n_rejected ?? 0}</span>
            </div>
            <div style={{ fontSize: '0.75rem', color: 'var(--red)', marginTop: '0.25rem' }}>
              Tỷ lệ từ chối: {(executionStats?.reject_rate * 100 || 0).toFixed(1)}%
            </div>
          </div>
          <div style={{ background: 'rgba(255,255,255,0.02)', padding: '1rem', borderRadius: '0.75rem', border: '1px solid rgba(255,255,255,0.06)' }}>
            <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Slippage Kỳ Vọng TB</div>
            <div style={{ fontSize: '1.6rem', fontWeight: 800, marginTop: '0.25rem', color: 'var(--accent)' }}>
              {executionStats?.avg_expected_slippage_bps?.toFixed(2) ?? '0.00'} <span style={{ fontSize: '0.9rem', fontWeight: 'normal' }}>bps</span>
            </div>
            <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginTop: '0.25rem' }}>
              Trung bình trên toàn bộ coin
            </div>
          </div>
          <div style={{ background: 'rgba(255,255,255,0.02)', padding: '1rem', borderRadius: '0.75rem', border: '1px solid rgba(255,255,255,0.06)' }}>
            <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Điểm Thanh Khoản TB</div>
            <div style={{ fontSize: '1.6rem', fontWeight: 800, marginTop: '0.25rem', color: 'var(--green)' }}>
              {executionStats?.avg_liquidity_score?.toFixed(2) ?? '0.00'}
            </div>
            <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginTop: '0.25rem' }}>
              Ngưỡng tối thiểu: {executionConfig?.min_liquidity_score ?? '0.4'}
            </div>
          </div>
          <div style={{ background: 'rgba(255,255,255,0.02)', padding: '1rem', borderRadius: '0.75rem', border: '1px solid rgba(255,255,255,0.06)' }}>
            <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Trạng Thế Engine</div>
            <div style={{ fontSize: '1.6rem', fontWeight: 800, marginTop: '0.25rem', color: '#a78bfa' }}>
              {executionConfig?.dry_run ? 'Dry Run 🧪' : 'Live Mode ⚡'}
            </div>
            <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginTop: '0.25rem' }}>
              Khớp lệnh mô phỏng giấy
            </div>
          </div>
        </div>

        {/* Row 2: Configurations & Simulator */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Column 1: Active Guards Config */}
          <div className="glass-panel lg:col-span-1" style={{ padding: '1.25rem', marginBottom: 0 }}>
            <h3 style={{ fontSize: '1rem', fontWeight: 'bold', marginBottom: '1rem', borderBottom: '1px solid rgba(255,255,255,0.06)', paddingBottom: '0.5rem' }}>Cổng Kiểm Soát Rủi Ro (Pre-trade Guards)</h3>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem', fontSize: '0.85rem' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', borderBottom: '1px solid rgba(255,255,255,0.03)', paddingBottom: '0.5rem' }}>
                <span style={{ color: 'var(--text-secondary)' }}>Max Spread cho phép:</span>
                <span style={{ fontWeight: 'bold', fontFamily: 'monospace' }}>{executionConfig?.max_spread_bps} bps</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', borderBottom: '1px solid rgba(255,255,255,0.03)', paddingBottom: '0.5rem' }}>
                <span style={{ color: 'var(--text-secondary)' }}>Max Slippage dự kiến:</span>
                <span style={{ fontWeight: 'bold', fontFamily: 'monospace' }}>{executionConfig?.max_slippage_bps} bps</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', borderBottom: '1px solid rgba(255,255,255,0.03)', paddingBottom: '0.5rem' }}>
                <span style={{ color: 'var(--text-secondary)' }}>Min Liquidity Score:</span>
                <span style={{ fontWeight: 'bold', fontFamily: 'monospace' }}>{executionConfig?.min_liquidity_score}</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', borderBottom: '1px solid rgba(255,255,255,0.03)', paddingBottom: '0.5rem' }}>
                <span style={{ color: 'var(--text-secondary)' }}>Max Latency cho phép:</span>
                <span style={{ fontWeight: 'bold', fontFamily: 'monospace' }}>{executionConfig?.max_latency_ms} ms</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', borderBottom: '1px solid rgba(255,255,255,0.03)', paddingBottom: '0.5rem' }}>
                <span style={{ color: 'var(--text-secondary)' }}>Tỷ lệ tham gia tối đa (ADV):</span>
                <span style={{ fontWeight: 'bold', fontFamily: 'monospace' }}>{((executionConfig?.max_participation_rate || 0.02) * 100).toFixed(1)}%</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', borderBottom: '1px solid rgba(255,255,255,0.03)', paddingBottom: '0.5rem' }}>
                <span style={{ color: 'var(--text-secondary)' }}>Phương pháp mặc định:</span>
                <span style={{ fontWeight: 'bold', color: '#3b82f6' }}>{executionConfig?.default_order_type}</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', paddingBottom: '0.25rem' }}>
                <span style={{ color: 'var(--text-secondary)' }}>TWAP Slices:</span>
                <span style={{ fontWeight: 'bold', fontFamily: 'monospace' }}>{executionConfig?.twap?.slices} slices ({executionConfig?.twap?.interval_seconds}s)</span>
              </div>
            </div>
          </div>

          {/* Column 2: Order Simulator */}
          <div className="glass-panel lg:col-span-2" style={{ padding: '1.25rem', marginBottom: 0 }}>
            <h3 style={{ fontSize: '1rem', fontWeight: 'bold', marginBottom: '1rem', borderBottom: '1px solid rgba(255,255,255,0.06)', paddingBottom: '0.5rem' }}>Trình Giả Lập Lệnh Giấy (Execution Simulator)</h3>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                <div>
                  <label style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', display: 'block', marginBottom: '0.25rem' }}>Coin</label>
                  <select
                    className="form-control"
                    style={{ background: 'rgba(0,0,0,0.3)', border: '1px solid var(--border-color)', borderRadius: '0.375rem', color: '#fff', padding: '0.4rem', width: '100%' }}
                    value={simulatorParams.coin}
                    onChange={(e) => setSimulatorParams({...simulatorParams, coin: e.target.value})}
                  >
                    {availableCoins.map(coin => <option key={coin} value={coin}>{coin}</option>)}
                  </select>
                </div>
                <div>
                  <label style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', display: 'block', marginBottom: '0.25rem' }}>Tín hiệu / Hướng đi</label>
                  <select
                    className="form-control"
                    style={{ background: 'rgba(0,0,0,0.3)', border: '1px solid var(--border-color)', borderRadius: '0.375rem', color: '#fff', padding: '0.4rem', width: '100%' }}
                    value={simulatorParams.signal_raw}
                    onChange={(e) => setSimulatorParams({...simulatorParams, signal_raw: e.target.value})}
                  >
                    <option value="BUY (Crossover)">BUY (Crossover)</option>
                    <option value="STRONG BUY (Confirmed Reversal)">STRONG BUY (Reversal)</option>
                    <option value="SELL (Crossover)">SELL (Crossover)</option>
                    <option value="STRONG SELL (Confirmed Reversal)">STRONG SELL (Reversal)</option>
                  </select>
                </div>
                <div>
                  <label style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', display: 'block', marginBottom: '0.25rem' }}>Giá đóng cửa (USDT)</label>
                  <input
                    type="number"
                    className="form-control"
                    style={{ background: 'rgba(0,0,0,0.3)', border: '1px solid var(--border-color)', borderRadius: '0.375rem', color: '#fff', padding: '0.4rem', width: '100%' }}
                    value={simulatorParams.close_price}
                    onChange={(e) => setSimulatorParams({...simulatorParams, close_price: e.target.value})}
                  />
                </div>
              </div>
              
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                <div>
                  <label style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', display: 'block', marginBottom: '0.25rem' }}>Volume nến</label>
                  <input
                    type="number"
                    className="form-control"
                    style={{ background: 'rgba(0,0,0,0.3)', border: '1px solid var(--border-color)', borderRadius: '0.375rem', color: '#fff', padding: '0.4rem', width: '100%' }}
                    value={simulatorParams.volume}
                    onChange={(e) => setSimulatorParams({...simulatorParams, volume: e.target.value})}
                  />
                </div>
                <div>
                  <label style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', display: 'block', marginBottom: '0.25rem' }}>Mức độ khẩn cấp (Urgency)</label>
                  <select
                    className="form-control"
                    style={{ background: 'rgba(0,0,0,0.3)', border: '1px solid var(--border-color)', borderRadius: '0.375rem', color: '#fff', padding: '0.4rem', width: '100%' }}
                    value={simulatorParams.urgency}
                    onChange={(e) => setSimulatorParams({...simulatorParams, urgency: e.target.value})}
                  >
                    <option value="NORMAL">NORMAL (Thường)</option>
                    <option value="HIGH">HIGH (Nhanh)</option>
                    <option value="EMERGENCY">EMERGENCY (Cắt lỗ khẩn cấp)</option>
                  </select>
                </div>
                <button
                  className="btn btn-primary w-full"
                  style={{ background: 'linear-gradient(to right, #3b82f6, #6366f1)', fontWeight: 'bold', marginTop: '1.2rem', padding: '0.5rem' }}
                  onClick={handleSimulateOrder}
                >
                  ⚡ Gửi Lệnh Giả Lập
                </button>
              </div>
            </div>
            {simulatorResult && (
              <div style={{ marginTop: '1rem', padding: '0.75rem', background: simulatorResult.status === 'REJECTED' ? 'rgba(239,68,68,0.1)' : 'rgba(34,197,94,0.1)', border: `1px solid ${simulatorResult.status === 'REJECTED' ? 'rgba(239,68,68,0.3)' : 'rgba(34,197,94,0.3)'}`, borderRadius: '0.375rem', fontSize: '0.8rem' }}>
                <div style={{ fontWeight: 'bold', color: simulatorResult.status === 'REJECTED' ? 'var(--red)' : 'var(--green)' }}>
                  {simulatorResult.status === 'REJECTED' ? '❌ LỆNH BỊ TỪ CHỐI (REJECTED)' : '✅ KHỚP LỆNH THÀNH CÔNG (FILLED)'}
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.5rem', marginTop: '0.5rem', fontFamily: 'monospace' }}>
                  <div>ID: #{simulatorResult.execution_id}</div>
                  <div>Loại: {simulatorResult.order_type}</div>
                  <div>Giá đặt: ${simulatorResult.submitted_price?.toFixed(2)}</div>
                  <div>Giá khớp TB: ${simulatorResult.avg_fill_price?.toFixed(2) || 'N/A'}</div>
                  <div>Điểm thanh khoản: {simulatorResult.liquidity_score?.toFixed(2)}</div>
                  <div>Chi phí Slippage: {simulatorResult.expected_slippage_bps?.toFixed(1)} bps</div>
                  {simulatorResult.reason && <div style={{ gridColumn: 'span 2', color: 'var(--text-secondary)' }}>Lý do: {simulatorResult.reason}</div>}
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Row 3: Quality report per Coin */}
        {executionReport?.by_coin && Object.keys(executionReport.by_coin).length > 0 && (
          <div className="glass-panel" style={{ padding: '1.25rem' }}>
            <h3 style={{ fontSize: '1.1rem', fontWeight: 'bold', marginBottom: '1rem' }}>Hiệu Suất Khớp Lệnh Theo Coin (Post-trade Shortfall)</h3>
            <div className="table-container">
              <table style={{ width: '100%' }}>
                <thead>
                  <tr>
                    <th>Coin</th>
                    <th style={{ textAlign: 'center' }}>Số Lượng Fills</th>
                    <th style={{ textAlign: 'right' }}>Shortfall TB (IS)</th>
                    <th style={{ textAlign: 'right' }}>Shortfall P95</th>
                    <th style={{ textAlign: 'right' }}>Lệch Sai Số Slippage</th>
                    <th>Phân Bổ Chất Lượng Khớp Lệnh</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(executionReport.by_coin).map(([coin, stats]) => (
                    <tr key={coin}>
                      <td style={{ fontWeight: 'bold' }}>{coin}</td>
                      <td style={{ textAlign: 'center', fontFamily: 'monospace' }}>{stats.n_fills}</td>
                      <td style={{ textAlign: 'right', fontFamily: 'monospace', color: stats.avg_is_bps > 15 ? 'var(--warning)' : 'var(--green)' }}>
                        {stats.avg_is_bps?.toFixed(2)} bps
                      </td>
                      <td style={{ textAlign: 'right', fontFamily: 'monospace', color: stats.p95_is_bps > 30 ? 'var(--red)' : 'var(--warning)' }}>
                        {stats.p95_is_bps?.toFixed(2)} bps
                      </td>
                      <td style={{ textAlign: 'right', fontFamily: 'monospace', color: stats.avg_slippage_prediction_error_bps >= 0 ? 'var(--red)' : 'var(--green)' }}>
                        {stats.avg_slippage_prediction_error_bps >= 0 ? '+' : ''}{stats.avg_slippage_prediction_error_bps?.toFixed(2)} bps
                      </td>
                      <td>
                        <div style={{ display: 'flex', height: '14px', borderRadius: '4px', overflow: 'hidden', minWidth: '150px', background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.08)' }}>
                          {stats.pct_excellent > 0 && <div style={{ width: `${stats.pct_excellent}%`, background: 'var(--green)' }} title={`Excellent: ${stats.pct_excellent}%`} />}
                          {stats.pct_good > 0 && <div style={{ width: `${stats.pct_good}%`, background: '#3b82f6' }} title={`Good: ${stats.pct_good}%`} />}
                          {stats.pct_poor > 0 && <div style={{ width: `${stats.pct_poor}%`, background: 'var(--red)' }} title={`Poor: ${stats.pct_poor}%`} />}
                        </div>
                        <div style={{ fontSize: '0.65rem', color: 'var(--text-secondary)', marginTop: '0.2rem', display: 'flex', gap: '0.4rem' }}>
                          <span style={{ color: 'var(--green)' }}>Ex: {stats.pct_excellent}%</span>
                          <span style={{ color: '#3b82f6' }}>Gd: {stats.pct_good}%</span>
                          <span style={{ color: 'var(--red)' }}>Pr: {stats.pct_poor}%</span>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Row 4: Recent Fills List */}
        <div className="glass-panel" style={{ padding: '1.25rem' }}>
          <h3 style={{ fontSize: '1.1rem', fontWeight: 'bold', marginBottom: '1rem' }}>Nhật Ký Các Vị Thế Khớp Lệnh Gần Đây</h3>
          {executionFills.length === 0 ? (
            <div className="text-secondary text-center py-6">Chưa có dữ liệu khớp lệnh.</div>
          ) : (
            <div className="table-container">
              <table>
                <thead>
                  <tr>
                    <th>Execution ID</th>
                    <th>Thời Gian</th>
                    <th>Coin</th>
                    <th>Hướng</th>
                    <th>Số lượng</th>
                    <th>Giá đặt nến</th>
                    <th>Giá khớp TB</th>
                    <th>Shortfall</th>
                    <th>Slippage Bps</th>
                    <th>Chất lượng</th>
                  </tr>
                </thead>
                <tbody>
                  {executionFills.map((fill) => {
                    const isB = fill.side && fill.side.toUpperCase() === 'BUY';
                    const is_bps = (fill.avg_fill_price - fill.decision_price) / fill.decision_price * 10000;
                    const shortfall = fill.side === 'BUY' ? is_bps : -is_bps;
                    
                    let ratingColor = 'var(--red)';
                    if (fill.quality_label === 'EXCELLENT') ratingColor = 'var(--green)';
                    if (fill.quality_label === 'GOOD') ratingColor = '#3b82f6';
                    
                    return (
                      <tr key={fill.execution_id}>
                        <td className="font-mono text-sm font-bold text-primary">#{fill.execution_id}</td>
                        <td>{new Date(fill.timestamp).toLocaleString()}</td>
                        <td style={{ fontWeight: 'bold' }}>{fill.coin}</td>
                        <td style={{ color: isB ? 'var(--green)' : 'var(--red)', fontWeight: 'bold' }}>{fill.side}</td>
                        <td className="font-mono">{fill.filled_qty?.toFixed(4)}</td>
                        <td className="font-mono">${fill.decision_price?.toFixed(2)}</td>
                        <td className="font-mono">${fill.avg_fill_price?.toFixed(2)}</td>
                        <td className="font-mono" style={{ color: shortfall > 15 ? 'var(--red)' : shortfall > 5 ? 'var(--warning)' : 'var(--green)', fontWeight: 'bold' }}>
                          {shortfall >= 0 ? '+' : ''}{shortfall?.toFixed(1)} bps
                        </td>
                        <td className="font-mono">{fill.expected_slippage_bps?.toFixed(1)} bps</td>
                        <td>
                          <span className="badge" style={{ background: ratingColor, color: '#fff', fontSize: '0.7rem' }}>
                            {fill.quality_label || 'GOOD'}
                          </span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    );
  };

  return (
    <div className="container">
      <div className="header">
        <div>
          <h1>BestTime Crypto</h1>
          <p className="text-secondary mt-1">Institutional Trading Dashboard</p>
        </div>
        <div className="flex gap-3">
          <button onClick={fetchData} className="btn" style={{ background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.1)' }}>
            <RefreshCw size={16} className={loading ? 'animate-spin' : ''} />
          </button>
          <button onClick={() => setShowAddModal(true)} className="btn btn-primary">
            <Plus size={16} /> Thêm Lệnh Mới
          </button>
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-8 gap-4 mb-6">
        <div className="glass-panel" style={{ cursor: 'pointer', padding: '1.25rem', marginBottom: 0, borderColor: activeTab === 'market' ? 'var(--accent)' : '' }} onClick={() => setActiveTab('market')}>
          <div className="stat-card">
            <div className="stat-title flex items-center gap-2"><Activity size={16} /> Tín Hiệu Thị Trường</div>
            <div className="stat-value">{Object.keys(signals).length} Pairs</div>
          </div>
        </div>
        <div className="glass-panel" style={{ cursor: 'pointer', padding: '1.25rem', marginBottom: 0, borderColor: activeTab === 'positions' ? 'var(--accent)' : '' }} onClick={() => setActiveTab('positions')}>
          <div className="stat-card">
            <div className="stat-title flex items-center gap-2"><Crosshair size={16} /> Vị Thế Đang Mở</div>
            <div className="stat-value">{positions.length}</div>
          </div>
        </div>
        <div className="glass-panel" style={{ cursor: 'pointer', padding: '1.25rem', marginBottom: 0, borderColor: activeTab === 'perf' ? 'var(--accent)' : '' }} onClick={() => setActiveTab('perf')}>
          <div className="stat-card">
            <div className="stat-title flex items-center gap-2"><Briefcase size={16} /> Win Rate</div>
            <div className="stat-value">{performance.win_rate_pct !== undefined ? `${performance.win_rate_pct}%` : 'N/A'}</div>
          </div>
        </div>
        <div className="glass-panel" style={{ cursor: 'pointer', padding: '1.25rem', marginBottom: 0, borderColor: activeTab === 'ai' ? 'var(--accent)' : '' }} onClick={() => setActiveTab('ai')}>
          <div className="stat-card">
            <div className="stat-title flex items-center gap-2"><Bot size={16} /> Gemini AI</div>
            <div className="stat-value text-blue-400">Phân Tích</div>
          </div>
        </div>
        <div className="glass-panel" style={{ cursor: 'pointer', padding: '1.25rem', marginBottom: 0, borderColor: activeTab === 'auto' ? 'var(--accent)' : '' }} onClick={() => setActiveTab('auto')}>
          <div className="stat-card">
            <div className="stat-title flex items-center gap-2"><Shield size={16} /> Auto Trading</div>
            <div className="stat-value text-purple-400">
              {autoTradeStatus ? (autoTradeStatus.mode === 'DRY_RUN' ? 'Dry Run' : 'Live') : 'Offline'}
            </div>
          </div>
        </div>
        <div className="glass-panel" style={{ cursor: 'pointer', padding: '1.25rem', marginBottom: 0, borderColor: activeTab === 'meta' ? 'var(--accent)' : '' }} onClick={() => setActiveTab('meta')}>
          <div className="stat-card">
            <div className="stat-title flex items-center gap-2"><Bot size={16} /> Meta Model</div>
            <div className="stat-value text-indigo-400">Huấn Luyện</div>
          </div>
        </div>
        <div className="glass-panel" style={{ cursor: 'pointer', padding: '1.25rem', marginBottom: 0, borderColor: activeTab === 'backtest' ? 'var(--accent)' : '' }} onClick={() => setActiveTab('backtest')}>
          <div className="stat-card">
            <div className="stat-title flex items-center gap-2"><Activity size={16} /> Backtesting</div>
            <div className="stat-value text-green-400">Kiểm thử</div>
          </div>
        </div>
        <div className="glass-panel" style={{ cursor: 'pointer', padding: '1.25rem', marginBottom: 0, borderColor: activeTab === 'execution' ? 'var(--accent)' : '' }} onClick={() => setActiveTab('execution')}>
          <div className="stat-card">
            <div className="stat-title flex items-center gap-2"><Shield size={16} /> Execution</div>
            <div className="stat-value text-indigo-400">Khớp lệnh</div>
          </div>
        </div>
      </div>

      <div className="glass-panel">
        <h2 className="text-xl font-bold mb-4 flex items-center gap-2">
          {activeTab === 'market' && <><Activity size={20} className="text-accent" /> Live Market Signals</>}
          {activeTab === 'positions' && <><Crosshair size={20} className="text-accent" /> Open Positions</>}
          {activeTab === 'perf' && <><Briefcase size={20} className="text-accent" /> Strategy Performance</>}
          {activeTab === 'ai' && <><Bot size={20} className="text-accent" /> Gemini AI Insights</>}
          {activeTab === 'auto' && <><Shield size={20} className="text-accent" /> CCXT Auto Trading Monitor</>}
          {activeTab === 'meta' && <><Bot size={20} className="text-indigo-400" /> Meta Model Analytics & Calibration</>}
          {activeTab === 'backtest' && <><Activity size={20} className="text-accent" /> Institutional Backtesting & Validation</>}
          {activeTab === 'execution' && <><Shield size={20} className="text-accent" /> Execution Intelligence & Quality Monitor</>}
        </h2>

        {activeTab === 'market' && renderMarketSignals()}
        {activeTab === 'positions' && renderPositions()}
        {activeTab === 'auto' && renderAutoTrade()}
        {activeTab === 'meta' && renderMetaModel()}
        {activeTab === 'backtest' && renderBacktesting()}
        {activeTab === 'execution' && renderExecution()}
        {activeTab === 'ai' && (
          <div className="p-6 bg-black/20 rounded-xl border border-blue-500/30">
            <div className="flex items-center gap-3 mb-4 border-b border-white/10 pb-4">
              <div className="w-10 h-10 rounded-full bg-blue-500/20 flex items-center justify-center text-blue-400">
                <Bot size={24} />
              </div>
              <div>
                <h3 className="text-lg font-bold text-blue-400">Phân tích thị trường từ Gemini</h3>
                {aiAnalysis?.timestamp > 0 && <div className="text-sm text-secondary">Cập nhật lúc: {new Date(aiAnalysis.timestamp * 1000).toLocaleString()}</div>}
              </div>
            </div>
            <div className="text-sm leading-relaxed text-slate-300 ai-markdown" style={{ padding: '1.5rem', background: 'rgba(0,0,0,0.4)', borderRadius: '0.5rem' }}>
              {aiAnalysis?.report ? (
                <ReactMarkdown>{aiAnalysis.report}</ReactMarkdown>
              ) : (
                'Đang chờ dữ liệu phân tích...'
              )}
            </div>
          </div>
        )}
        {activeTab === 'perf' && (() => {
          const currentPerf = perfTab === 'AUTO' ? perfAuto : perfTab === 'MANUAL' ? perfManual : performance;
          return (
            <div>
              <div className="flex gap-2 mb-6" style={{ background: 'rgba(0,0,0,0.2)', padding: '0.25rem', borderRadius: '0.5rem', width: 'fit-content' }}>
                <button
                  className={`btn ${perfTab === 'ALL' ? 'bg-accent' : ''}`}
                  style={{ background: perfTab === 'ALL' ? 'rgba(56, 189, 248, 0.2)' : 'transparent', color: perfTab === 'ALL' ? '#38bdf8' : 'var(--text-secondary)', border: 'none' }}
                  onClick={() => setPerfTab('ALL')}
                >
                  Tất Cả (All)
                </button>
                <button
                  className={`btn ${perfTab === 'AUTO' ? 'bg-accent' : ''}`}
                  style={{ background: perfTab === 'AUTO' ? 'rgba(167, 139, 250, 0.2)' : 'transparent', color: perfTab === 'AUTO' ? '#a78bfa' : 'var(--text-secondary)', border: 'none' }}
                  onClick={() => setPerfTab('AUTO')}
                >
                  <Bot size={16} className="inline mr-1" /> Bot (Auto)
                </button>
                <button
                  className={`btn ${perfTab === 'MANUAL' ? 'bg-accent' : ''}`}
                  style={{ background: perfTab === 'MANUAL' ? 'rgba(56, 189, 248, 0.2)' : 'transparent', color: perfTab === 'MANUAL' ? '#38bdf8' : 'var(--text-secondary)', border: 'none' }}
                  onClick={() => setPerfTab('MANUAL')}
                >
                  <Shield size={16} className="inline mr-1" /> Người dùng (Manual)
                </button>
              </div>

              {currentPerf?.message ? (
                <div className="text-secondary text-center py-8">{currentPerf.message}</div>
              ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                  <div>
                    <table className="w-full">
                      <tbody>
                        <tr><td className="text-secondary">Tổng số lệnh</td><td className="font-bold">{currentPerf.total_trades || 0}</td></tr>
                        <tr><td className="text-secondary">Số lệnh Thắng / Thua</td><td className="font-bold">{currentPerf.wins || 0} / {currentPerf.losses || 0}</td></tr>
                        <tr><td className="text-secondary">Lãi trung bình (Win)</td><td className="font-bold text-green">+{currentPerf.avg_win_pct || 0}%</td></tr>
                        <tr><td className="text-secondary">Lỗ trung bình (Loss)</td><td className="font-bold text-red">{currentPerf.avg_loss_pct || 0}%</td></tr>
                        <tr><td className="text-secondary">Kỳ vọng (Avg R)</td><td className="font-bold">{currentPerf.avg_r_multiplier || 'N/A'}R</td></tr>
                      </tbody>
                    </table>
                  </div>
                  <div>
                    <div className="p-6 bg-black/20 rounded-xl border border-white/5 flex flex-col items-center justify-center h-full">
                      <div className="text-secondary mb-2">Tổng Lợi Nhuận (PnL)</div>
                      <div className={`text-4xl font-bold ${currentPerf.total_pnl_pct >= 0 ? 'text-green' : 'text-red'}`}>
                        {currentPerf.total_pnl_pct > 0 ? '+' : ''}{currentPerf.total_pnl_pct || 0}%
                      </div>
                      <div className="text-secondary mt-4">Max Drawdown (Chuỗi Thua)</div>
                      <div className="text-xl font-bold text-red">{currentPerf.max_consecutive_losses || 0} lệnh</div>
                      <div className="text-secondary mt-4">Lãi/Lỗ Thực Tế (USDT)</div>
                      <div className={`text-xl font-bold ${currentPerf.total_pnl_usd_actual >= 0 ? 'text-green' : 'text-red'}`}>
                        {currentPerf.total_pnl_usd_actual > 0 ? '+' : ''}${currentPerf.total_pnl_usd_actual || 0}
                      </div>
                    </div>
                  </div>
                </div>
              )}
            </div>
          );
        })()}
      </div>

      {showAddModal && (
        <div className="modal-overlay">
          <div className="modal-content">
            <div className="modal-header">
              <h3 className="modal-title">Thêm Vị Thế Mới</h3>
              <button className="close-btn" onClick={() => setShowAddModal(false)}><X size={20} /></button>
            </div>
            <form onSubmit={handleAddPosition}>
              <div className="form-group">
                <label className="form-label">Tên Coin</label>
                <select className="form-control" value={newPos.coin} onChange={e => setNewPos({ ...newPos, coin: e.target.value })}>
                  {availableCoins.map(c => (
                    <option key={c} value={c}>{c}</option>
                  ))}
                </select>
              </div>
              <div className="form-group">
                <label className="form-label">Giá Khớp Lệnh (Entry)</label>
                <input required type="number" step="any" className="form-control" value={newPos.entry_price} onChange={e => setNewPos({ ...newPos, entry_price: e.target.value })} />
              </div>
              <div className="form-group">
                <label className="form-label">Số vốn bỏ ra (USDT)</label>
                <input type="number" step="any" className="form-control" value={newPos.invested_usdt} onChange={e => setNewPos({ ...newPos, invested_usdt: e.target.value })} placeholder="VD: 100" />
              </div>
              <div className="form-group">
                <label className="form-label">Hướng (Spot = LONG)</label>
                <select className="form-control" value={newPos.direction} onChange={e => setNewPos({ ...newPos, direction: e.target.value })}>
                  <option value="LONG">LONG (Mua / Spot)</option>
                  <option value="SHORT">SHORT (Bán Khống)</option>
                </select>
              </div>
              <div className="form-group">
                <label className="form-label">Ghi Chú</label>
                <input className="form-control" value={newPos.note} onChange={e => setNewPos({ ...newPos, note: e.target.value })} placeholder="VD: Mua theo tín hiệu SFP" />
              </div>
              <div className="form-group">
                <label className="form-label">Cơ sở vào lệnh</label>
                <select className="form-control" value={newPos.manual_decision_basis} onChange={e => setNewPos({ ...newPos, manual_decision_basis: e.target.value })}>
                  <option value="personal_discretion">Quyết định cá nhân</option>
                  <option value="system_signal">Theo tín hiệu hệ thống</option>
                </select>
              </div>
              {newPos.manual_decision_basis === 'system_signal' && (
                <div className="form-group">
                  <label className="form-label">Signal ID (tùy chọn)</label>
                  <input className="form-control" value={newPos.signal_id} onChange={e => setNewPos({ ...newPos, signal_id: e.target.value })} placeholder="Tín hiệu đã dẫn tới lệnh này" />
                </div>
              )}
              <button type="submit" className="btn btn-primary w-full mt-4">Thêm Vị Thế</button>
            </form>
          </div>
        </div>
      )}

      {showCloseModal && (
        <div className="modal-overlay">
          <div className="modal-content">
            <div className="modal-header">
              <h3 className="modal-title">Đóng Lệnh {showCloseModal}</h3>
              <button className="close-btn" onClick={() => setShowCloseModal(null)}><X size={20} /></button>
            </div>
            <form onSubmit={handleClosePosition}>
              <div className="form-group">
                <label className="form-label">Giá Đóng Lệnh (Sell Price)</label>
                <input required type="number" step="any" className="form-control" value={closePrice} onChange={e => setClosePrice(e.target.value)} />
              </div>
              <button type="submit" className="btn btn-primary w-full mt-4">Xác Nhận Đóng Lệnh</button>
            </form>
          </div>
        </div>
      )}

      {showPartialModal && (
        <div className="modal-overlay">
          <div className="modal-content">
            <div className="modal-header">
              <h3 className="modal-title">Chốt Lời 1 Phần {showPartialModal}</h3>
              <button className="close-btn" onClick={() => setShowPartialModal(null)}><X size={20} /></button>
            </div>
            <form onSubmit={handlePartialClose}>
              <div className="form-group">
                <label className="form-label">Phần Trăm Chốt (%)</label>
                <input required type="number" min="1" max="99" step="any" className="form-control" value={partialPercentage} onChange={e => setPartialPercentage(e.target.value)} />
                <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.5rem' }}>
                  {[25, 50, 75].map(pct => (
                    <button key={pct} type="button" onClick={() => setPartialPercentage(pct)} className="btn flex-1" style={{ fontSize: '0.8rem', padding: '0.2rem' }}>{pct}%</button>
                  ))}
                </div>
              </div>
              <div className="form-group">
                <label className="form-label">Giá Đóng Lệnh (Sell Price)</label>
                <input required type="number" step="any" className="form-control" value={partialPrice} onChange={e => setPartialPrice(e.target.value)} />
              </div>
              <button type="submit" className="btn w-full mt-4" style={{ background: 'linear-gradient(to right, #38bdf8, #818cf8)' }}>Xác Nhận Chốt Lời</button>
            </form>
          </div>
        </div>
      )}

      {renderDetailModal()}

    </div>
  );
}

export default App;
