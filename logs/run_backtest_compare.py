#!/usr/bin/env python3
import glob,shutil,os,subprocess,csv
from datetime import datetime

def main():
    now=datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
    cfg_path='btc_scraper/regime_config.json'
    backups=sorted(glob.glob('logs/regime_config_autoapply_backup_*.json'))
    if not backups:
        print('No autoapply backup found in logs/')
        return 2
    backup=backups[-1]
    print('Using backup:',backup)
    # save current
    cur_saved=f'logs/regime_config_after_apply_{now}.json'
    shutil.copyfile(cfg_path, cur_saved)
    print('Saved current config ->',cur_saved)
    # copy backup into place (before apply state)
    shutil.copyfile(backup, cfg_path)
    print('Restored backup into',cfg_path)
    # run backtest (before)
    print('\nRunning backtest (before apply)')
    subprocess.run(['.venv/bin/python','-m','btc_scraper.regime_backtest'], check=True)
    # copy outputs
    src_csv='btc_scraper/regime_stats_detailed.csv'
    src_json='btc_scraper/regime_stats.json'
    before_csv=f'logs/regime_stats_before_apply_{now}.csv'
    before_json=f'logs/regime_stats_before_apply_{now}.json'
    if os.path.exists(src_csv): shutil.copyfile(src_csv,before_csv); print('Saved',before_csv)
    else: print('Missing',src_csv)
    if os.path.exists(src_json): shutil.copyfile(src_json,before_json); print('Saved',before_json)
    else: print('Missing',src_json)
    # restore current config
    shutil.copyfile(cur_saved, cfg_path)
    print('\nRestored current config ->',cfg_path)
    # run backtest (after)
    print('\nRunning backtest (after apply)')
    subprocess.run(['.venv/bin/python','-m','btc_scraper.regime_backtest'], check=True)
    # copy outputs
    after_csv=f'logs/regime_stats_after_apply_{now}.csv'
    after_json=f'logs/regime_stats_after_apply_{now}.json'
    if os.path.exists(src_csv): shutil.copyfile(src_csv,after_csv); print('Saved',after_csv)
    else: print('Missing',src_csv)
    if os.path.exists(src_json): shutil.copyfile(src_json,after_json); print('Saved',after_json)
    else: print('Missing',src_json)

    # compute simple PnL sums from CSVs
    def sum_pnl(path):
        if not os.path.exists(path):
            return None
        s_total=0.0
        per_regime={}
        with open(path,'r',encoding='utf-8') as f:
            reader=csv.DictReader(f)
            for r in reader:
                try:
                    total=int(r.get('total', r.get('count',0)) or 0)
                except:
                    total=0
                try:
                    avg_pnl=float(r.get('avg_pnl', r.get('avgPnl',0)) or 0)
                except:
                    avg_pnl=0.0
                row_pnl = total * avg_pnl
                s_total += row_pnl
                regime = r.get('regime') or r.get('Regime') or 'UNKNOWN'
                per_regime.setdefault(regime,0.0)
                per_regime[regime] += row_pnl
        return s_total, per_regime

    before = sum_pnl(before_csv)
    after = sum_pnl(after_csv)
    print('\nSummary:')
    if before is None:
        print('Before CSV missing:', before_csv)
    else:
        print('Before total approx pnl:', round(before[0],6))
        print('Before per regime:', {k:round(v,6) for k,v in before[1].items()})
    if after is None:
        print('After CSV missing:', after_csv)
    else:
        print('After total approx pnl:', round(after[0],6))
        print('After per regime:', {k:round(v,6) for k,v in after[1].items()})
    if before and after:
        diff = after[0]-before[0]
        pct = (diff/before[0]*100) if before[0]!=0 else None
        print('\nDelta (after - before):', round(diff,6), ('({:.2f}% )'.format(pct) if pct is not None else '(no baseline pct)'))
    return 0

if __name__=='__main__':
    exit(main())
