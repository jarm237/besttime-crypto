import { useState, useEffect } from 'react';
import axios from 'axios';
import { LineChart, Activity, Briefcase, Plus, X, RefreshCw, Crosshair, TrendingUp, TrendingDown, Bot } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import './index.css';

const API_BASE = 'http://localhost:8000/api';

function App() {
  const [activeTab, setActiveTab] = useState('market');
  const [signals, setSignals] = useState({});
  const [positions, setPositions] = useState([]);
  const [performance, setPerformance] = useState({});
  const [availableCoins, setAvailableCoins] = useState(['BTC', 'ETH', 'SOL', 'BNB', 'XRP']);
  const [aiAnalysis, setAiAnalysis] = useState(null);
  const [loading, setLoading] = useState(true);
  const [showAddModal, setShowAddModal] = useState(false);
  const [showCloseModal, setShowCloseModal] = useState(null);
  const [showDetailModal, setShowDetailModal] = useState(null);

  const [newPos, setNewPos] = useState({ coin: 'BTC', entry_price: '', direction: 'LONG', note: '', invested_usdt: '' });
  const [closePrice, setClosePrice] = useState('');

  const fetchData = async () => {
    setLoading(true);
    try {
      const [sigRes, posRes, perfRes, confRes, aiRes] = await Promise.all([
        axios.get(`${API_BASE}/market-signals`).catch(() => ({ data: { signals: {} } })),
        axios.get(`${API_BASE}/positions`).catch(() => ({ data: { positions: [] } })),
        axios.get(`${API_BASE}/performance`).catch(() => ({ data: { performance: {} } })),
        axios.get(`${API_BASE}/config`).catch(() => ({ data: { coins: [] } })),
        axios.get(`${API_BASE}/ai-analysis`).catch(() => ({ data: { report: 'Lỗi tải dữ liệu AI', timestamp: 0 } }))
      ]);
      setSignals(sigRes.data.signals || {});
      setPositions(posRes.data.positions || []);
      setPerformance(perfRes.data.performance || {});
      setAiAnalysis(aiRes.data);
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
        <div onClick={e => e.stopPropagation()} style={{
          background: '#111827', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '1rem',
          width: '100%', maxWidth: '780px', maxHeight: '90vh', overflowY: 'auto',
          boxShadow: '0 25px 50px rgba(0,0,0,0.7)'
        }}>

          {/* ── HEADER ── */}
          <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center', padding:'1.25rem 1.5rem', borderBottom:'1px solid rgba(255,255,255,0.08)' }}>
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
              <div style={{ color:'#64748b', fontSize:'0.78rem', display:'flex', alignItems:'center', gap:'0.4rem' }}>
                <span>🕐</span> Cập nhật: {ts}
              </div>
              <button onClick={() => setShowDetailModal(null)} style={{ background:'none', border:'none', color:'#94a3b8', cursor:'pointer', fontSize:'1.2rem', lineHeight:1 }}>✕</button>
            </div>
          </div>

          <div style={{ padding:'1.25rem 1.5rem', display:'flex', flexDirection:'column', gap:'1rem' }}>

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
          <button onClick={fetchData} className="btn" style={{ background: 'rgba(255,255,255,0.1)' }}>
            <RefreshCw size={16} className={loading ? 'animate-spin' : ''} /> 
          </button>
          <button onClick={() => setShowAddModal(true)} className="btn btn-primary">
            <Plus size={16} /> Thêm Lệnh Mới
          </button>
        </div>
      </div>

      <div className="grid grid-cols-4 mb-6">
        <div className="glass-panel" style={{ cursor: 'pointer', border: activeTab === 'market' ? '1px solid var(--accent)' : '' }} onClick={() => setActiveTab('market')}>
          <div className="stat-card">
            <div className="stat-title flex items-center gap-2"><Activity size={16} /> Tín Hiệu Thị Trường</div>
            <div className="stat-value">{Object.keys(signals).length} Pairs</div>
          </div>
        </div>
        <div className="glass-panel" style={{ cursor: 'pointer', border: activeTab === 'positions' ? '1px solid var(--accent)' : '' }} onClick={() => setActiveTab('positions')}>
          <div className="stat-card">
            <div className="stat-title flex items-center gap-2"><Crosshair size={16} /> Vị Thế Đang Mở</div>
            <div className="stat-value">{positions.length}</div>
          </div>
        </div>
        <div className="glass-panel" style={{ cursor: 'pointer', border: activeTab === 'perf' ? '1px solid var(--accent)' : '' }} onClick={() => setActiveTab('perf')}>
          <div className="stat-card">
            <div className="stat-title flex items-center gap-2"><Briefcase size={16} /> Win Rate</div>
            <div className="stat-value">{performance.win_rate_pct !== undefined ? `${performance.win_rate_pct}%` : 'N/A'}</div>
          </div>
        </div>
        <div className="glass-panel" style={{ cursor: 'pointer', border: activeTab === 'ai' ? '1px solid var(--accent)' : '' }} onClick={() => setActiveTab('ai')}>
          <div className="stat-card">
            <div className="stat-title flex items-center gap-2"><Bot size={16} /> Gemini AI</div>
            <div className="stat-value text-blue-400">Phân Tích</div>
          </div>
        </div>
      </div>

      <div className="glass-panel">
        <h2 className="text-xl font-bold mb-4 flex items-center gap-2">
          {activeTab === 'market' && <><Activity size={20} className="text-accent"/> Live Market Signals</>}
          {activeTab === 'positions' && <><Crosshair size={20} className="text-accent"/> Open Positions</>}
          {activeTab === 'perf' && <><Briefcase size={20} className="text-accent"/> Strategy Performance</>}
          {activeTab === 'ai' && <><Bot size={20} className="text-accent"/> Gemini AI Insights</>}
        </h2>

        {activeTab === 'market' && renderMarketSignals()}
        {activeTab === 'positions' && renderPositions()}
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
        {activeTab === 'perf' && (
          <div className="grid grid-cols-1 md:grid-cols-2">
            <div>
              <table className="w-full">
                <tbody>
                  <tr><td className="text-secondary">Tổng số lệnh</td><td className="font-bold">{performance.total_trades || 0}</td></tr>
                  <tr><td className="text-secondary">Số lệnh Thắng / Thua</td><td className="font-bold">{performance.wins || 0} / {performance.losses || 0}</td></tr>
                  <tr><td className="text-secondary">Lãi trung bình (Win)</td><td className="font-bold text-green">+{performance.avg_win_pct || 0}%</td></tr>
                  <tr><td className="text-secondary">Lỗ trung bình (Loss)</td><td className="font-bold text-red">{performance.avg_loss_pct || 0}%</td></tr>
                  <tr><td className="text-secondary">Kỳ vọng (Avg R)</td><td className="font-bold">{performance.avg_r_multiplier || 'N/A'}R</td></tr>
                </tbody>
              </table>
            </div>
            <div>
              <div className="p-6 bg-black/20 rounded-xl border border-white/5 flex flex-col items-center justify-center h-full">
                <div className="text-secondary mb-2">Tổng Lợi Nhuận (PnL)</div>
                <div className={`text-4xl font-bold ${performance.total_pnl_pct >= 0 ? 'text-green' : 'text-red'}`}>
                  {performance.total_pnl_pct > 0 ? '+' : ''}{performance.total_pnl_pct || 0}%
                </div>
                <div className="text-secondary mt-4">Max Drawdown (Chuỗi Thua)</div>
                <div className="text-xl font-bold text-red">{performance.max_consecutive_losses || 0} lệnh</div>
                <div className="text-secondary mt-4">Lãi/Lỗ Thực Tế (USDT)</div>
                <div className={`text-xl font-bold ${performance.total_pnl_usd_actual >= 0 ? 'text-green' : 'text-red'}`}>
                  {performance.total_pnl_usd_actual > 0 ? '+' : ''}${performance.total_pnl_usd_actual || 0}
                </div>
              </div>
            </div>
          </div>
        )}
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
