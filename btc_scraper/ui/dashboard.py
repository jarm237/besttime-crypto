"""
Minimal FastAPI dashboard to expose current market regime and metrics.

Endpoints:
 - GET /regime -> JSON with latest regime info (reads logs/market_regime_latest.json)
 - GET / -> simple HTML page showing regime and quick stats

Run: `uvicorn btc_scraper.dashboard:app --reload --port 8001`
"""
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, HTMLResponse
from pathlib import Path
import json

app = FastAPI(title="Market Regime Dashboard")

REGIME_PATH = Path(__file__).parent.parent / "logs" / "market_regime_latest.json"
REGIME_CONFIG = Path(__file__).parent / "regime_config.json"
LABEL_QUALITY_PATH = Path(__file__).resolve().parents[2] / "data" / "feature_store" / "labels" / "label_quality_report.json"


def _load_latest():
  if not REGIME_PATH.exists():
    return {"error": "no_data", "message": str(REGIME_PATH)}
  try:
    with open(REGIME_PATH, "r") as f:
      data = json.load(f)
    # attach last modified timestamp
    try:
      mtime = REGIME_PATH.stat().st_mtime
      from datetime import datetime

      data["updated_at"] = datetime.utcfromtimestamp(mtime).isoformat() + "Z"
    except Exception:
      pass
    return data
  except Exception as e:
    return {"error": "read_error", "message": str(e)}


@app.get("/regime", response_class=JSONResponse)
def get_regime():
    return _load_latest()


@app.get("/multipliers", response_class=JSONResponse)
def get_multipliers():
    # return position_size_multipliers section from regime_config.json
    if not REGIME_CONFIG.exists():
        return {"position_size_multipliers": {"default": {}, "per_strategy": {}}}
    try:
        with open(REGIME_CONFIG, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        return cfg.get("position_size_multipliers", {"default": {}, "per_strategy": {}})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

@app.get("/tuning", response_class=JSONResponse)
def get_tuning():
    tuning_path = Path(__file__).parent.parent / "logs" / "multiplier_tuning.json"
    if not tuning_path.exists():
        return {"message": "no_tuning"}
    try:
        with open(tuning_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

@app.get("/meta_model", response_class=JSONResponse)
def get_meta_model():
    """Return meta model metrics and existence state."""
    metrics_path = Path(__file__).parent.parent / "logs" / "meta_model.json"
    model_path = Path(__file__).parent.parent / "logs" / "meta_model.joblib"
    importance_path = Path(__file__).parent.parent / "logs" / "meta_feature_importance.json"
    if not metrics_path.exists() and not model_path.exists():
        return {"message": "no_meta_model"}
    out = {"model_exists": model_path.exists()}
    try:
        if metrics_path.exists():
            with open(metrics_path, "r", encoding="utf-8") as f:
                out["metrics"] = json.load(f)
    except Exception as e:
        out["metrics_error"] = str(e)
    try:
        if importance_path.exists():
            with open(importance_path, "r", encoding="utf-8") as f:
                out["feature_importance"] = json.load(f)
    except Exception as e:
        out["importance_error"] = str(e)
    return out


@app.get("/label_quality", response_class=JSONResponse)
def get_label_quality():
    """Return latest Phase 8 label quality report."""
    if not LABEL_QUALITY_PATH.exists():
        return {
            "message": "no_label_quality_report",
            "path": str(LABEL_QUALITY_PATH),
        }
    try:
        with open(LABEL_QUALITY_PATH, "r", encoding="utf-8") as f:
            report = json.load(f)
        report["source_path"] = str(LABEL_QUALITY_PATH)
        return report
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/meta_model/predict", response_class=JSONResponse)
async def meta_model_predict(request: Request):
    """Accept a JSON record and return meta model probability."""
    try:
        body = await request.json()
    except Exception as e:
        return JSONResponse({"error": "invalid_json", "message": str(e)}, status_code=400)
    try:
        from btc_scraper.ml_engine.meta_model import predict_meta_confidence
        res = predict_meta_confidence(body)
        return res
    except Exception as e:
        return JSONResponse({"error": "predict_failed", "message": str(e)}, status_code=500)


@app.post("/multipliers/apply_suggestion", response_class=JSONResponse)
def apply_suggestion():
    tuning_path = Path(__file__).parent.parent / "logs" / "multiplier_tuning.json"
    cfg_path = Path(__file__).with_name("regime_config.json")
    if not tuning_path.exists():
        return JSONResponse({"error": "no_tuning_file"}, status_code=400)
    try:
        with open(tuning_path, "r", encoding="utf-8") as f:
            t = json.load(f)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

    suggested = None
    if isinstance(t, dict) and t.get("suggested"):
        suggested = t["suggested"]
    elif isinstance(t, dict) and t.get("top"):
        # take top[0].multipliers as default mapping
        top = t.get("top")
        if top:
            suggested = {"default": top[0].get("multipliers", {}), "per_strategy": {}}

    if not suggested:
        return JSONResponse({"error": "no_suggestion_in_tuning"}, status_code=400)

    # load existing cfg
    cfg = {}
    try:
        if cfg_path.exists():
            with open(cfg_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
    except Exception:
        cfg = {}

    cfg["position_size_multipliers"] = suggested
    try:
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
        return {"ok": True}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.put("/multipliers", response_class=JSONResponse)
async def put_multipliers(request: Request):
    try:
        body = await request.json()
        # merge into existing config file
        cfg = {}
        if REGIME_CONFIG.exists():
            try:
                with open(REGIME_CONFIG, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
            except Exception:
                cfg = {}
        cfg["position_size_multipliers"] = body
        with open(REGIME_CONFIG, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
        return {"ok": True}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    d = _load_latest()
    regime = d.get("regime", "-")
    conf = d.get("confidence", "-")
    adx = d.get("adx", "-")
    atr = d.get("atr_pct", "-")
    # Build a dynamic page that polls /regime and updates UI
    html = """
    <!doctype html>
    <html>
    <head>
      <meta charset="utf-8" />
      <meta name="viewport" content="width=device-width,initial-scale=1" />
      <title>Market Regime Dashboard</title>
      <style>
        :root {{ --bg:#071025; --card:#0c1724; --muted:#9fb4d6; --accent:#78c2a8; --danger:#e05b5b; --warn:#f2b844; --orange:#f97316 }}
        body {{ margin:0; font-family: Inter, system-ui, -apple-system, Arial; background:linear-gradient(180deg,#041225 0%, #07102a 100%); color:#e6eef8; display:flex; align-items:center; justify-content:center; height:100vh }}
        .wrap {{ width:min(760px, 96%); }}
        .card {{ background:var(--card); padding:20px; border-radius:12px; box-shadow: 0 6px 20px rgba(2,6,23,0.6) }}
        .header {{ display:flex; align-items:center; justify-content:space-between; gap:12px }}
        .title {{ font-size:18px; color:var(--muted) }}
        .regime {{ font-size:28px; font-weight:700 }}
        .badge {{ display:inline-block; padding:8px 12px; border-radius:999px; font-weight:700 }}
        .meta {{ margin-top:12px; color:var(--muted); display:flex; gap:12px; flex-wrap:wrap }}
        .stat {{ background:rgba(255,255,255,0.02); padding:10px 12px; border-radius:8px; min-width:120px }}
        .conf-bar {{ height:10px; background:#071223; border-radius:999px; overflow:hidden; margin-top:8px }}
        .conf-fill {{ height:100%; background:linear-gradient(90deg,var(--accent),var(--orange)); width:0% }}
        pre.json {{ margin-top:12px; background:#03101a; padding:10px; border-radius:8px; color:#9fb4d6; max-height:160px; overflow:auto }}
      </style>
    </head>
    <body>
      <div class="wrap">
        <div class="card">
          <div class="header">
            <div>
              <div class="title">BTC — Market Regime</div>
              <div style="display:flex;align-items:center;gap:12px;margin-top:8px">
                <div class="regime" id="regimeLabel">%%REGIME%%</div>
                <div id="regimeBadge" class="badge" style="background:#334155">&nbsp;</div>
                <div style="color:var(--muted);">Confidence: <span id="confPercent">%%CONF_PERCENT%%%</span></div>
              </div>
              <div class="conf-bar"><div id="confFill" class="conf-fill" style="width:%%CONF_FILL_WIDTH%%"></div></div>
            </div>
            <div style="text-align:right">
              <div style="color:var(--muted);">Last update</div>
              <div id="lastUpdated" style="font-weight:600">%%UPDATED_AT%%</div>
            </div>
          </div>

          <div class="meta">
            <div class="stat">ADX: <strong id="adxVal">%%ADX%%</strong></div>
            <div class="stat">ATR: <strong id="atrVal">%%ATR%%%</strong></div>
            <div class="stat">SMA200: <strong id="sma200Val">%%SMA200%%</strong></div>
            <div class="stat">EMA21: <strong id="ema21Val">%%EMA21%%</strong></div>
          </div>

          <pre id="rawJson" class="json">%%RAW_JSON%%</pre>
        </div>
        
        <div class="card" style="margin-top:12px">
          <div style="display:flex;justify-content:space-between;align-items:center">
            <div style="font-size:16px;color:var(--muted);font-weight:700">Position Size Multipliers</div>
            <div style="color:var(--muted);font-size:12px">Edit JSON and click Save</div>
          </div>
          <div style="margin-top:10px">
            <textarea id="multipliersArea" style="width:100%;height:160px;background:#02121a;color:#cfe8ff;border-radius:8px;padding:8px;border:1px solid rgba(255,255,255,0.04)"></textarea>
            <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:8px">
              <button id="reloadBtn" style="padding:8px 12px;border-radius:8px;border:none;background:#334155;color:#e6eef8">Reload</button>
              <button id="saveBtn" style="padding:8px 12px;border-radius:8px;border:none;background:linear-gradient(90deg,var(--accent),var(--orange));color:#071025">Save</button>
            </div>
            <div id="saveMsg" style="color:var(--muted);margin-top:8px;font-size:13px"></div>
          </div>
        </div>

        <div class="card" style="margin-top:12px">
          <div style="display:flex;justify-content:space-between;align-items:center">
            <div style="font-size:16px;color:var(--muted);font-weight:700">Suggested Multipliers (Tuning)</div>
            <div style="color:var(--muted);font-size:12px">Based on latest tuning</div>
          </div>
          <div style="margin-top:10px">
            <pre id="suggestedArea" style="width:100%;height:140px;background:#02121a;color:#cfe8ff;border-radius:8px;padding:8px;border:1px solid rgba(255,255,255,0.04);overflow:auto">Loading...</pre>
            <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:8px">
              <button id="refreshSuggestBtn" style="padding:8px 12px;border-radius:8px;border:none;background:#334155;color:#e6eef8">Refresh</button>
              <button id="applySuggestBtn" style="padding:8px 12px;border-radius:8px;border:none;background:#0bbd7a;color:#071025">Apply Suggested</button>
            </div>
            <div id="applyMsg" style="color:var(--muted);margin-top:8px;font-size:13px"></div>
          </div>
        </div>

        <div class="card" style="margin-top:12px">
          <div style="display:flex;justify-content:space-between;align-items:center">
            <div style="font-size:16px;color:var(--muted);font-weight:700">Phase 8 Label Quality</div>
            <div style="color:var(--muted);font-size:12px">Auto-loaded from label_quality_report.json</div>
          </div>
          <div class="meta" style="margin-top:10px">
            <div class="stat">Triple rows: <strong id="lqTripleRows">-</strong></div>
            <div class="stat">Meta rows: <strong id="lqMetaRows">-</strong></div>
            <div class="stat">Trade rows: <strong id="lqTradeRows">-</strong></div>
            <div class="stat">Exec rate: <strong id="lqExecRate">-</strong></div>
            <div class="stat">Meta rate: <strong id="lqMetaRate">-</strong></div>
            <div class="stat">Imbalance: <strong id="lqImbalance">-</strong></div>
            <div class="stat">Warnings: <strong id="lqWarningsCount">-</strong></div>
          </div>
          <div style="margin-top:10px;display:flex;gap:10px;flex-wrap:wrap">
            <pre id="lqDistTriple" class="json" style="flex:1;min-width:220px;max-height:120px">{}</pre>
            <pre id="lqDistMeta" class="json" style="flex:1;min-width:220px;max-height:120px">{}</pre>
            <pre id="lqDistTrade" class="json" style="flex:1;min-width:220px;max-height:120px">{}</pre>
          </div>
          <pre id="lqWarnings" class="json" style="margin-top:10px;max-height:100px">[]</pre>
        </div>
      </div>

      <script>
        const badge = document.getElementById('regimeBadge');
        const label = document.getElementById('regimeLabel');
        const confFill = document.getElementById('confFill');
        const confPercent = document.getElementById('confPercent');
        const lastUpdated = document.getElementById('lastUpdated');
        const rawJson = document.getElementById('rawJson');

        function colorForRegime(r){
          switch((r||'').toUpperCase()){
            case 'TRENDING_BULL': return ['#052e16','#1bd98b'];
            case 'TRENDING_BEAR': return ['#330b0b','#ff7b7b'];
            case 'RANGING': return ['#2b2f3a','#f2b844'];
            case 'HIGH_VOLATILITY': return ['#2a1f12','#ff9f43'];
            default: return ['#334155','#9fb4d6'];
          }
        }

        async function refresh(){
          try{
            const res = await fetch('/regime');
            const j = await res.json();
            label.textContent = j.regime || '-';
            const c = (typeof j.confidence === 'number') ? Math.round(j.confidence*100) : (j.confidence||0);
            confFill.style.width = c + '%';
            confPercent.textContent = c + '%';
            document.getElementById('adxVal').textContent = j.adx || '-';
            document.getElementById('atrVal').textContent = (j.atr_pct !== undefined ? (j.atr_pct + '%') : (j.atr_pct || '-'));
            document.getElementById('sma200Val').textContent = j.sma200 || '-';
            document.getElementById('ema21Val').textContent = j.ema21 || '-';
            lastUpdated.textContent = j.updated_at || new Date().toISOString();
            rawJson.textContent = JSON.stringify(j, null, 2);
            const colors = colorForRegime(j.regime);
            badge.style.background = colors[0];
            badge.style.color = colors[1];
            badge.textContent = j.regime ? j.regime.replace('_',' ') : '';
          }catch(e){
            console.error('refresh err',e);
          }
        }

        // initial and poll
        setTimeout(refresh, 200);
        setInterval(refresh, 5000);

        // multipliers editor
        const multipliersArea = document.getElementById('multipliersArea');
        const saveBtn = document.getElementById('saveBtn');
        const reloadBtn = document.getElementById('reloadBtn');
        const saveMsg = document.getElementById('saveMsg');

        async function loadMultipliers(){
          try{
            const r = await fetch('/multipliers');
            const j = await r.json();
            multipliersArea.value = JSON.stringify(j, null, 2);
            saveMsg.textContent = '';
          }catch(e){
            multipliersArea.value = '{}';
            saveMsg.textContent = 'Failed to load multipliers';
          }
        }

        async function saveMultipliers(){
          try{
            const parsed = JSON.parse(multipliersArea.value);
            const r = await fetch('/multipliers', {method:'PUT', headers:{'Content-Type':'application/json'}, body: JSON.stringify(parsed)});
            const j = await r.json();
            if(j && j.ok){
              saveMsg.textContent = 'Saved.';
            }else{
              saveMsg.textContent = 'Save failed: ' + JSON.stringify(j);
            }
          }catch(e){
            saveMsg.textContent = 'Invalid JSON: ' + e.message;
          }
        }

        reloadBtn.addEventListener('click', loadMultipliers);
        saveBtn.addEventListener('click', saveMultipliers);
        setTimeout(loadMultipliers, 400);

        // suggested multipliers
        const suggestedArea = document.getElementById('suggestedArea');
        const refreshSuggestBtn = document.getElementById('refreshSuggestBtn');
        const applySuggestBtn = document.getElementById('applySuggestBtn');
        const applyMsg = document.getElementById('applyMsg');

        // label quality panel
        function fmtPct(v){
          if (typeof v !== 'number') return '-';
          return (v * 100).toFixed(2) + '%';
        }

        async function loadLabelQuality(){
          try{
            const r = await fetch('/label_quality');
            const j = await r.json();
            if(j && j.message === 'no_label_quality_report'){
              document.getElementById('lqWarnings').textContent = JSON.stringify([j.message], null, 2);
              return;
            }

            const counts = j.counts || {};
            const metrics = j.quality_metrics || {};
            const dist = j.distributions || {};
            const warnings = Array.isArray(j.warnings) ? j.warnings : [];

            document.getElementById('lqTripleRows').textContent = String(counts.triple_barrier_rows ?? '-');
            document.getElementById('lqMetaRows').textContent = String(counts.meta_label_rows ?? '-');
            document.getElementById('lqTradeRows').textContent = String(counts.trade_quality_rows ?? '-');
            document.getElementById('lqExecRate').textContent = fmtPct(metrics.executable_signal_rate);
            document.getElementById('lqMetaRate').textContent = fmtPct(metrics.meta_execute_rate);
            document.getElementById('lqImbalance').textContent = (typeof metrics.meta_class_imbalance_ratio === 'number') ? metrics.meta_class_imbalance_ratio.toFixed(3) : '-';
            document.getElementById('lqWarningsCount').textContent = String(warnings.length);

            document.getElementById('lqDistTriple').textContent = JSON.stringify(dist.triple_barrier_label || {}, null, 2);
            document.getElementById('lqDistMeta').textContent = JSON.stringify(dist.meta_label || {}, null, 2);
            document.getElementById('lqDistTrade').textContent = JSON.stringify(dist.trade_quality_bucket || {}, null, 2);
            document.getElementById('lqWarnings').textContent = JSON.stringify(warnings, null, 2);
          }catch(e){
            document.getElementById('lqWarnings').textContent = JSON.stringify(['label_quality_fetch_failed', String(e)], null, 2);
          }
        }

        async function loadSuggested(){
          try{
            const r = await fetch('/tuning');
            const j = await r.json();
            suggestedArea.textContent = JSON.stringify(j, null, 2);
            applyMsg.textContent = '';
          }catch(e){
            suggestedArea.textContent = 'No tuning results';
          }
        }

        async function applySuggested(){
          try{
            const r = await fetch('/multipliers/apply_suggestion', {method:'POST'});
            const j = await r.json();
            if(j && j.ok){
              applyMsg.textContent = 'Applied suggested multipliers to config.';
              setTimeout(loadMultipliers, 400);
            }else{
              applyMsg.textContent = 'Apply failed: ' + JSON.stringify(j);
            }
          }catch(e){
            applyMsg.textContent = 'Apply error: ' + e.message;
          }
        }

        refreshSuggestBtn.addEventListener('click', loadSuggested);
        applySuggestBtn.addEventListener('click', applySuggested);
        setTimeout(loadSuggested, 600);
        setTimeout(loadLabelQuality, 700);
        setInterval(loadLabelQuality, 8000);
      </script>
    </body>
    </html>
      """

    # inject values safely (avoid f-string brace issues)
    try:
        conf_pct = int(conf * 100) if isinstance(conf, (int, float)) else conf
    except Exception:
        conf_pct = conf
    html = html.replace('%%REGIME%%', str(regime))
    html = html.replace('%%CONF_PERCENT%%', str(conf_pct))
    html = html.replace('%%CONF_FILL_WIDTH%%', str(conf_pct) + '%')
    html = html.replace('%%UPDATED_AT%%', str(d.get('updated_at', '-')))
    html = html.replace('%%ADX%%', str(adx))
    html = html.replace('%%ATR%%', str(atr))
    html = html.replace('%%SMA200%%', str(d.get('sma200', '-')))
    html = html.replace('%%EMA21%%', str(d.get('ema21', '-')))
    html = html.replace('%%RAW_JSON%%', json.dumps(d, indent=2))

    return HTMLResponse(content=html)
