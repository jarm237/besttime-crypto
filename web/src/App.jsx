import { useState, useEffect } from 'react';
import axios from 'axios';
import { LineChart, Activity, Briefcase, Plus, X, RefreshCw, Crosshair, TrendingUp, TrendingDown, Bot, Shield, AlertTriangle } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import './index.css';

const API_BASE = 'http://localhost:8000/api';

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
  const [loading, setLoading] = useState(true);
  const [showAddModal, setShowAddModal] = useState(false);
  const [showCloseModal, setShowCloseModal] = useState(null);
  const [showDetailModal, setShowDetailModal] = useState(null);

  const [newPos, setNewPos] = useState({ coin: 'BTC', entry_price: '', direction: 'LONG', note: '', invested_usdt: '' });
  const [closePrice, setClosePrice] = useState('');

  const fetchData = async () => {
    setLoading(true);
    try {
      const [sigRes, posRes, perfRes, confRes, aiRes, autoStatusRes, autoLogsRes] = await Promise.all([
        axios.get(`${API_BASE}/market-signals`).catch(() => ({ data: { signals: {} } })),
        axios.get(`${API_BASE}/positions`).catch(() => ({ data: { positions: [] } })),
        axios.get(`${API_BASE}/performance`).catch(() => ({ data: { performance: {} } })),
        axios.get(`${API_BASE}/config`).catch(() => ({ data: { coins: [] } })),
        axios.get(`${API_BASE}/ai-analysis`).catch(() => ({ data: { report: 'Lỗi tải dữ liệu AI', timestamp: 0 } })),
        axios.get(`${API_BASE}/auto-trade/status`).catch(() => ({ data: null })),
        axios.get(`${API_BASE}/auto-trade/logs`).catch(() => ({ data: [] }))
      ]);
      setSignals(sigRes.data.signals || {});
      setPositions(posRes.data.positions || []);
      setPerformance(perfRes.data.performance || {});
      setPerfAuto(perfRes.data.performance_auto || {});
      setPerfManual(perfRes.data.performance_manual || {});
      setAiAnalysis(aiRes.data);
      setAutoTradeStatus(autoStatusRes.data);
      setAutoTradeLogs(autoLogsRes.data || []);
      if (confRes.data.coins && confRes.data.coins.length > 0) {
        setAvailableCoins(confRes.data.coins);
        setNewPos(prev => ({ 
          ...prev, 
          coin: confRes.data.coins.includes(prev.coin) ? prev.coin : confRes.data.coins[0] 
        }));
      }
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
      setNewPos({ coin: 'BTC', entry_price: '', direction: 'LONG', note: '', invested_usdt: '' });
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
                  </tr>
                </thead>
                <tbody>
                  {[...autoTradeLogs].reverse().map((log, i) => {
                    const isSkipped = log.status === 'skipped';
                    const isError = log.status === 'error';
                    const isSuccess = !isSkipped && !isError;
                    
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
                        <td className="font-mono">{(log.meta_confidence * 100).toFixed(0)}% (Score: {log.signal_score})</td>
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
                  <td className="font-mono">${data.close?.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 4})}</td>
                  <td className={`font-mono ${data.rsi < 30 ? 'text-green' : data.rsi > 70 ? 'text-red' : ''}`}>
                    {data.rsi?.toFixed(1)}
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
                      const metaPct = data.signal_score?.meta_confidence_pct;
                      if (metaPct == null) return <span style={{ color: '#475569', fontSize: '0.8rem' }}>N/A</span>;
                      const color = metaPct >= 70 ? '#22c55e' : metaPct >= 50 ? '#f59e0b' : '#ef4444';
                      return (
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                          <div style={{ width: 36, height: 36, borderRadius: '50%', border: `2px solid ${color}`, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '0.75rem', fontWeight: 700, color }}>
                            {metaPct}%
                          </div>
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
              </div>

              <button 
                onClick={() => setShowCloseModal(pos.coin)}
                className="btn btn-danger w-full"
              >
                <X size={16} /> Đóng Vị Thế
              </button>
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
    const ts = `${now.getHours().toString().padStart(2,'0')}:${now.getMinutes().toString().padStart(2,'0')} ${now.getDate().toString().padStart(2,'0')}/${(now.getMonth()+1).toString().padStart(2,'0')}/${now.getFullYear()}`;

    const signalColor = isBuy ? '#22c55e' : isSell ? '#ef4444' : '#f59e0b';
    const signalIcon = isBuy ? '▲' : isSell ? '▼' : '⚠';
    const signalBg = isBuy ? 'rgba(34,197,94,0.08)' : isSell ? 'rgba(239,68,68,0.08)' : 'rgba(245,158,11,0.08)';
    const signalBorder = isBuy ? 'rgba(34,197,94,0.25)' : isSell ? 'rgba(239,68,68,0.25)' : 'rgba(245,158,11,0.25)';

    return (
      <div className="modal-overlay" onClick={() => setShowDetailModal(null)}>
        <div onClick={e => e.stopPropagation()} className="modal-content" style={{ maxWidth: '850px', padding: 0 }}>

          {/* ── HEADER ── */}
          <div className="modal-header" style={{ padding: '1.5rem', marginBottom: 0, borderBottom: '1px solid var(--border-color)', background: 'rgba(0,0,0,0.2)', borderTopLeftRadius: '1.5rem', borderTopRightRadius: '1.5rem' }}>
            <div style={{ display:'flex', alignItems:'center', gap:'0.75rem' }}>
              <div style={{ width:40, height:40, borderRadius:'50%', background:'linear-gradient(135deg,#f0b90b,#f8d47a)', display:'flex', alignItems:'center', justifyContent:'center', fontSize:'1.1rem', fontWeight:700, color:'#000' }}>
                {coin.slice(0,2)}
              </div>
              <div>
                <div style={{ fontWeight:700, fontSize:'1.3rem' }}>{coin}/USDT</div>
                <div style={{ color:'#94a3b8', fontSize:'0.8rem' }}>Chi Tiết Tín Hiệu</div>
              </div>
            </div>
            <div style={{ display:'flex', alignItems:'center', gap:'1rem' }}>
              <div style={{ color:'var(--text-secondary)', fontSize:'0.8rem', display:'flex', alignItems:'center', gap:'0.4rem' }}>
                <span>🕐</span> Cập nhật: {ts}
              </div>
              <button className="close-btn" onClick={() => setShowDetailModal(null)}>✕</button>
            </div>
          </div>

          <div style={{ padding:'1.5rem', display:'flex', flexDirection:'column', gap:'1.25rem', maxHeight: 'calc(90vh - 85px)', overflowY: 'auto' }}>

            {/* ── ROW 1: Signal + Price ── */}
            <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:'1rem' }}>

              {/* Signal block */}
              <div style={{ background: signalBg, border:`1px solid ${signalBorder}`, borderRadius:'0.75rem', padding:'1.25rem' }}>
                <div style={{ fontSize:'0.7rem', color:'#94a3b8', textTransform:'uppercase', letterSpacing:'0.08em', marginBottom:'0.75rem' }}>TÍN HIỆU HIỆN TẠI</div>
                <div style={{ display:'flex', alignItems:'flex-start', gap:'0.75rem', marginBottom:'0.75rem' }}>
                  <div style={{ width:44, height:44, borderRadius:'50%', background:'rgba(0,0,0,0.3)', border:`2px solid ${signalColor}`, display:'flex', alignItems:'center', justifyContent:'center', fontSize:'1.3rem', color:signalColor, flexShrink:0 }}>
                    {signalIcon}
                  </div>
                  <div style={{ color:signalColor, fontWeight:800, fontSize:'1.05rem', lineHeight:1.3 }}>{data.signal}</div>
                </div>
                <div style={{ color:'#94a3b8', fontSize:'0.8rem', lineHeight:1.6 }}>{data.reason || 'Phân tích đa chỉ báo'}</div>
                <div style={{ marginTop:'0.75rem', paddingTop:'0.75rem', borderTop:'1px solid rgba(255,255,255,0.06)', display:'flex', justifyContent:'space-between', fontSize:'0.8rem' }}>
                  <span style={{ color:'#64748b' }}>CÁC CHỈ BÁO KỸ THUẬT</span>
                  <span style={{ color:data.rsi < 30 ? '#22c55e' : data.rsi > 70 ? '#ef4444' : '#f59e0b', fontWeight:600 }}>RSI: {data.rsi?.toFixed(1)}</span>
                </div>
              </div>

              {/* Price block */}
              <div style={{ background:'rgba(255,255,255,0.03)', border:'1px solid rgba(255,255,255,0.08)', borderRadius:'0.75rem', padding:'1.25rem' }}>
                <div style={{ fontSize:'0.7rem', color:'#94a3b8', textTransform:'uppercase', letterSpacing:'0.08em', marginBottom:'0.75rem' }}>GIÁ / HỖ TRỢ / KHÁNG CỰ</div>
                <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr 1fr', gap:'0.5rem', marginBottom:'1rem', textAlign:'center' }}>
                  <div>
                    <div style={{ fontSize:'0.7rem', color:'#ef4444', marginBottom:'0.25rem' }}>Kháng cự (Res)</div>
                    <div style={{ fontFamily:'monospace', fontWeight:700, color:'#ef4444', fontSize:'1.05rem' }}>${res.toFixed(2)}</div>
                  </div>
                  <div>
                    <div style={{ fontSize:'0.7rem', color:'#94a3b8', marginBottom:'0.25rem' }}>Giá hiện tại</div>
                    <div style={{ fontFamily:'monospace', fontWeight:700, color:'#f8fafc', fontSize:'1.05rem' }}>${data.close?.toFixed(2)}</div>
                  </div>
                  <div>
                    <div style={{ fontSize:'0.7rem', color:'#22c55e', marginBottom:'0.25rem' }}>Hỗ trợ (Sup)</div>
                    <div style={{ fontFamily:'monospace', fontWeight:700, color:'#22c55e', fontSize:'1.05rem' }}>${sup.toFixed(2)}</div>
                  </div>
                </div>
                {/* Slider */}
                <div style={{ position:'relative', height:6, borderRadius:999, background:'linear-gradient(to right, #ef4444, #f8fafc 50%, #22c55e)', marginBottom:'0.5rem' }}>
                  <div style={{ position:'absolute', top:'50%', left:`${100 - pricePos}%`, transform:'translate(-50%,-50%)', width:14, height:14, borderRadius:'50%', background:'#fff', border:'2px solid #1e293b', boxShadow:'0 0 6px rgba(255,255,255,0.6)' }} />
                </div>
                <div style={{ display:'flex', justifyContent:'space-between', fontSize:'0.7rem', color:'#64748b', fontFamily:'monospace' }}>
                  <span>{res.toFixed(2)}</span><span>{data.close?.toFixed(2)}</span><span>{sup.toFixed(2)}</span>
                </div>
              </div>
            </div>

            {/* ── ROW 2: Indicators + TP/SL ── */}
            <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:'1rem' }}>

              {/* Indicators */}
              <div style={{ background:'rgba(255,255,255,0.03)', border:'1px solid rgba(255,255,255,0.08)', borderRadius:'0.75rem', padding:'1.25rem' }}>
                <div style={{ fontSize:'0.7rem', color:'#3b82f6', textTransform:'uppercase', letterSpacing:'0.08em', marginBottom:'1rem', display:'flex', alignItems:'center', gap:'0.4rem' }}>
                  <span>📈</span> CHỈ BÁO KỸ THUẬT
                </div>
                {[
                  ['EMA 9:', data.ema9?.toFixed(2), 'ATR (14):', data.atr?.toFixed(2)],
                  ['EMA 21:', data.ema21?.toFixed(2), 'MACD (12,26,9):', data.macd?.toFixed(2)],
                  ['SMA 50:', data.sma50?.toFixed(2), 'BB Mid (20,2):', data.bb_middle?.toFixed(2)],
                  ['SMA 200:', data.sma200?.toFixed(2) || '0.00', 'RSI (14):', data.rsi?.toFixed(1)],
                ].map(([l1,v1,l2,v2], i) => (
                  <div key={i} style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:'0.5rem', paddingBottom:'0.6rem', marginBottom:'0.6rem', borderBottom: i < 3 ? '1px solid rgba(255,255,255,0.05)' : 'none' }}>
                    <div style={{ display:'flex', justifyContent:'space-between', paddingRight:'0.75rem' }}>
                      <span style={{ color:'#94a3b8', fontSize:'0.85rem' }}>{l1}</span>
                      <span style={{ fontFamily:'monospace', fontSize:'0.85rem', color:'#a78bfa', fontWeight:600 }}>{v1}</span>
                    </div>
                    <div style={{ display:'flex', justifyContent:'space-between', paddingLeft:'0.75rem', borderLeft:'1px solid rgba(255,255,255,0.06)' }}>
                      <span style={{ color:'#94a3b8', fontSize:'0.85rem' }}>{l2}</span>
                      <span style={{ fontFamily:'monospace', fontSize:'0.85rem', color: v2 < 0 ? '#ef4444' : '#a78bfa', fontWeight:600 }}>{v2}</span>
                    </div>
                  </div>
                ))}
              </div>

              {/* TP/SL Plan */}
              <div style={{ background:'rgba(255,255,255,0.03)', border:'1px solid rgba(255,255,255,0.08)', borderRadius:'0.75rem', padding:'1.25rem' }}>
                <div style={{ fontSize:'0.7rem', color:'#22c55e', textTransform:'uppercase', letterSpacing:'0.08em', marginBottom:'1rem', display:'flex', alignItems:'center', gap:'0.4rem' }}>
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
                  <div key={i} style={{ display:'flex', justifyContent:'space-between', alignItems:'center', paddingBottom:'0.65rem', marginBottom:'0.65rem', borderBottom: i < 6 ? '1px solid rgba(255,255,255,0.05)' : 'none' }}>
                    <span style={{ color:'#94a3b8', fontSize:'0.85rem' }}>{label}</span>
                    <div style={{ display:'flex', alignItems:'center', gap:'0.6rem' }}>
                      <span style={{ fontFamily:'monospace', fontWeight:600, color, fontSize:'0.9rem' }}>{isDollar && val ? `$${val}` : val}</span>
                      {i === 2 && data.tp_sl?.rr1 && <span style={{ color:'#64748b', fontSize:'0.75rem' }}>(RR: {data.tp_sl.rr1}R)</span>}
                      {i === 3 && data.tp_sl?.rr2 && <span style={{ color:'#64748b', fontSize:'0.75rem' }}>(RR: {data.tp_sl.rr2}R)</span>}
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* ── ROW 3: 4 bottom stat cards ── */}
            <div style={{ display:'grid', gridTemplateColumns:'repeat(4,1fr)', gap:'0.75rem' }}>
              {[
                { icon:'↔', color:'#a78bfa', label:'XU HƯỚNG', value: regime, desc: regimeTxt },
                { icon:'📈', color:'#f59e0b', label:'ĐỘ BIẾN ĐỘNG', value: volLabel, desc: `ATR: ${data.atr?.toFixed(2)}\n${volDesc}` },
                { icon:'📊', color:'#3b82f6', label:'KHUNG THỜI GIAN', value: '4H', desc: 'Phân tích theo khung 4 giờ' },
                { icon:'🛡', color:'#22c55e', label:'RỦI RO', value: riskLabel, desc: riskDesc },
              ].map((card, i) => (
                <div key={i} style={{ background:'rgba(255,255,255,0.03)', border:'1px solid rgba(255,255,255,0.08)', borderRadius:'0.75rem', padding:'1rem' }}>
                  <div style={{ display:'flex', alignItems:'center', gap:'0.5rem', marginBottom:'0.5rem' }}>
                    <div style={{ width:32, height:32, borderRadius:'50%', background:`rgba(${i===0?'167,139,250':i===1?'245,158,11':i===2?'59,130,246':'34,197,94'},0.15)`, display:'flex', alignItems:'center', justifyContent:'center', fontSize:'0.9rem' }}>{card.icon}</div>
                    <div style={{ fontSize:'0.65rem', color:card.color, textTransform:'uppercase', letterSpacing:'0.06em', fontWeight:600 }}>{card.label}</div>
                  </div>
                  <div style={{ fontWeight:700, fontSize:'1.1rem', color:'#f8fafc', marginBottom:'0.25rem' }}>{card.value}</div>
                  <div style={{ color:'#64748b', fontSize:'0.75rem', lineHeight:1.4, whiteSpace:'pre-line' }}>{card.desc}</div>
                </div>
              ))}
            </div>

            {/* ── ROW 4: Meta Model Panel ── */}
            {(() => {
              const metaPct = data.signal_score?.meta_confidence_pct;
              const metaErr = data.signal_score?.meta_error;
              if (metaPct == null && !metaErr) return null;
              const metaColor = metaPct >= 70 ? '#22c55e' : metaPct >= 50 ? '#f59e0b' : '#ef4444';
              const metaLabel = metaPct >= 70 ? 'Xác suất cao — Tín hiệu đáng tin' : metaPct >= 50 ? 'Xác suất trung bình — Thận trọng' : 'Xác suất thấp — Nên bỏ qua';
              const metaBg = metaPct >= 70 ? 'rgba(34,197,94,0.06)' : metaPct >= 50 ? 'rgba(245,158,11,0.06)' : 'rgba(239,68,68,0.06)';
              const metaBorder = metaPct >= 70 ? 'rgba(34,197,94,0.2)' : metaPct >= 50 ? 'rgba(245,158,11,0.2)' : 'rgba(239,68,68,0.2)';
              return (
                <div style={{ background: metaBg, border: `1px solid ${metaBorder}`, borderRadius:'0.75rem', padding:'1.25rem' }}>
                  <div style={{ fontSize:'0.7rem', color:'#a78bfa', textTransform:'uppercase', letterSpacing:'0.08em', marginBottom:'1rem', display:'flex', alignItems:'center', gap:'0.4rem' }}>
                    <span>🤖</span> META MODEL CONFIDENCE (RandomForest)
                  </div>
                  {metaPct != null ? (
                    <div style={{ display:'flex', alignItems:'center', gap:'1.5rem' }}>
                      {/* Circular gauge */}
                      <div style={{ position:'relative', width:80, height:80, flexShrink:0 }}>
                        <svg viewBox="0 0 80 80" style={{ width:'100%', height:'100%', transform:'rotate(-90deg)' }}>
                          <circle cx="40" cy="40" r="34" fill="none" stroke="rgba(255,255,255,0.08)" strokeWidth="8"/>
                          <circle cx="40" cy="40" r="34" fill="none" stroke={metaColor} strokeWidth="8"
                            strokeDasharray={`${2 * Math.PI * 34 * metaPct / 100} ${2 * Math.PI * 34 * (1 - metaPct/100)}`}
                            strokeLinecap="round"
                          />
                        </svg>
                        <div style={{ position:'absolute', inset:0, display:'flex', flexDirection:'column', alignItems:'center', justifyContent:'center' }}>
                          <div style={{ fontSize:'1.2rem', fontWeight:800, color: metaColor }}>{metaPct}%</div>
                        </div>
                      </div>
                      <div style={{ flex:1 }}>
                        <div style={{ fontWeight:700, color: metaColor, fontSize:'1rem', marginBottom:'0.35rem' }}>{metaLabel}</div>
                        <div style={{ color:'#64748b', fontSize:'0.78rem', lineHeight:1.5 }}>
                          Xác suất thắng dự đoán từ lịch sử giao dịch.
                          Giai đoạn hiện tại: <b style={{ color:'#a78bfa' }}>Shadow Mode</b> — chỉ hiển thị, chưa can thiệp.
                        </div>
                        {/* Progress bar */}
                        <div style={{ marginTop:'0.75rem', height:6, borderRadius:999, background:'rgba(255,255,255,0.06)' }}>
                          <div style={{ height:'100%', borderRadius:999, background:`linear-gradient(to right, #ef4444, #f59e0b 50%, #22c55e)`, width:`${metaPct}%`, transition:'width 0.5s' }} />
                        </div>
                        <div style={{ display:'flex', justifyContent:'space-between', fontSize:'0.65rem', color:'#475569', marginTop:'0.2rem' }}>
                          <span>0%</span><span>50%</span><span>100%</span>
                        </div>
                      </div>
                    </div>
                  ) : (
                    <div style={{ color:'#64748b', fontSize:'0.85rem' }}>
                      ⚠️ {metaErr === 'no_model' ? 'Model chưa được train. Chạy: python -m btc_scraper.meta_model --train' : `Lỗi: ${metaErr}`}
                    </div>
                  )}
                </div>
              );
            })()}

            {/* Footer */}
            <div style={{ background:'rgba(59,130,246,0.06)', border:'1px solid rgba(59,130,246,0.15)', borderRadius:'0.5rem', padding:'0.65rem 1rem', fontSize:'0.78rem', color:'#64748b', display:'flex', alignItems:'center', gap:'0.5rem' }}>
              <span>ℹ️</span> Lưu ý: Tín hiệu mang tính chất tham khảo. Quản trị rủi ro và kỷ luật là yếu tố quan trọng.
            </div>

          </div>
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

      <div className="grid grid-cols-5 mb-6">
        <div className="glass-panel" style={{ cursor: 'pointer', padding: '1.25rem', borderColor: activeTab === 'market' ? 'var(--accent)' : '' }} onClick={() => setActiveTab('market')}>
          <div className="stat-card">
            <div className="stat-title flex items-center gap-2"><Activity size={16} /> Tín Hiệu Thị Trường</div>
            <div className="stat-value">{Object.keys(signals).length} Pairs</div>
          </div>
        </div>
        <div className="glass-panel" style={{ cursor: 'pointer', padding: '1.25rem', borderColor: activeTab === 'positions' ? 'var(--accent)' : '' }} onClick={() => setActiveTab('positions')}>
          <div className="stat-card">
            <div className="stat-title flex items-center gap-2"><Crosshair size={16} /> Vị Thế Đang Mở</div>
            <div className="stat-value">{positions.length}</div>
          </div>
        </div>
        <div className="glass-panel" style={{ cursor: 'pointer', padding: '1.25rem', borderColor: activeTab === 'perf' ? 'var(--accent)' : '' }} onClick={() => setActiveTab('perf')}>
          <div className="stat-card">
            <div className="stat-title flex items-center gap-2"><Briefcase size={16} /> Win Rate</div>
            <div className="stat-value">{performance.win_rate_pct !== undefined ? `${performance.win_rate_pct}%` : 'N/A'}</div>
          </div>
        </div>
        <div className="glass-panel" style={{ cursor: 'pointer', padding: '1.25rem', borderColor: activeTab === 'ai' ? 'var(--accent)' : '' }} onClick={() => setActiveTab('ai')}>
          <div className="stat-card">
            <div className="stat-title flex items-center gap-2"><Bot size={16} /> Gemini AI</div>
            <div className="stat-value text-blue-400">Phân Tích</div>
          </div>
        </div>
        <div className="glass-panel" style={{ cursor: 'pointer', padding: '1.25rem', borderColor: activeTab === 'auto' ? 'var(--accent)' : '' }} onClick={() => setActiveTab('auto')}>
          <div className="stat-card">
            <div className="stat-title flex items-center gap-2"><Shield size={16} /> Auto Trading</div>
            <div className="stat-value text-purple-400">
              {autoTradeStatus ? (autoTradeStatus.mode === 'DRY_RUN' ? 'Dry Run' : 'Live') : 'Offline'}
            </div>
          </div>
        </div>
      </div>

      <div className="glass-panel">
        <h2 className="text-xl font-bold mb-4 flex items-center gap-2">
          {activeTab === 'market' && <><Activity size={20} className="text-accent"/> Live Market Signals</>}
          {activeTab === 'positions' && <><Crosshair size={20} className="text-accent"/> Open Positions</>}
          {activeTab === 'perf' && <><Briefcase size={20} className="text-accent"/> Strategy Performance</>}
          {activeTab === 'ai' && <><Bot size={20} className="text-accent"/> Gemini AI Insights</>}
          {activeTab === 'auto' && <><Shield size={20} className="text-accent"/> CCXT Auto Trading Monitor</>}
        </h2>

        {activeTab === 'market' && renderMarketSignals()}
        {activeTab === 'positions' && renderPositions()}
        {activeTab === 'auto' && renderAutoTrade()}
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
                  <Bot size={16} className="inline mr-1"/> Bot (Auto)
                </button>
                <button 
                  className={`btn ${perfTab === 'MANUAL' ? 'bg-accent' : ''}`} 
                  style={{ background: perfTab === 'MANUAL' ? 'rgba(56, 189, 248, 0.2)' : 'transparent', color: perfTab === 'MANUAL' ? '#38bdf8' : 'var(--text-secondary)', border: 'none' }}
                  onClick={() => setPerfTab('MANUAL')}
                >
                  <Shield size={16} className="inline mr-1"/> Người dùng (Manual)
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
                <select className="form-control" value={newPos.coin} onChange={e => setNewPos({...newPos, coin: e.target.value})}>
                  {availableCoins.map(c => (
                    <option key={c} value={c}>{c}</option>
                  ))}
                </select>
              </div>
              <div className="form-group">
                <label className="form-label">Giá Khớp Lệnh (Entry)</label>
                <input required type="number" step="any" className="form-control" value={newPos.entry_price} onChange={e => setNewPos({...newPos, entry_price: e.target.value})} />
              </div>
              <div className="form-group">
                <label className="form-label">Số vốn bỏ ra (USDT)</label>
                <input type="number" step="any" className="form-control" value={newPos.invested_usdt} onChange={e => setNewPos({...newPos, invested_usdt: e.target.value})} placeholder="VD: 100" />
              </div>
              <div className="form-group">
                <label className="form-label">Hướng (Spot = LONG)</label>
                <select className="form-control" value={newPos.direction} onChange={e => setNewPos({...newPos, direction: e.target.value})}>
                  <option value="LONG">LONG (Mua / Spot)</option>
                  <option value="SHORT">SHORT (Bán Khống)</option>
                </select>
              </div>
              <div className="form-group">
                <label className="form-label">Ghi Chú</label>
                <input className="form-control" value={newPos.note} onChange={e => setNewPos({...newPos, note: e.target.value})} placeholder="VD: Mua theo tín hiệu SFP" />
              </div>
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

      {renderDetailModal()}

    </div>
  );
}

export default App;
