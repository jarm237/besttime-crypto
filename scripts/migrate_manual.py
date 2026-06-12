import json
import os

def migrate_file(filepath):
    if not os.path.exists(filepath):
        print(f"File not found: {filepath}")
        return
        
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
        
    updated = 0
    for pos in data:
        note = pos.get('note', '')
        if '[AUTO-' not in note and '[MANUAL]' not in note:
            pos['note'] = f"[MANUAL] {note}".strip()
            updated += 1
            
    if updated > 0:
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"Migrated {updated} positions in {filepath}")
    else:
        print(f"No positions needed migration in {filepath}")

migrate_file('data/positions.json')
migrate_file('logs/closed_positions.json')
