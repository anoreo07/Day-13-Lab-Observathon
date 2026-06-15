#!/usr/bin/env python3
"""
Generate 120 public questions from the scorer's answer key.
Each question is synthesized from the spec (item, qty, coupon, dest)
to produce a natural-language Vietnamese order question that the
agent/wrapper can process.
"""
import json
import re

# Parse the disassembled answer key to extract all 120 specs
ANSWER_KEY_FILE = "/Users/haiannguyen/pyinstxtractor/observathon-score_extracted/dis_answerkey.txt"

def parse_answer_key(path):
    """Parse bytecode disassembly to extract QID -> spec mappings."""
    with open(path, 'r') as f:
        content = f.read()
    
    # Find all QID entries: LOAD_CONST  N ('pub-NNN')
    qid_pattern = re.compile(r"LOAD_CONST\s+\d+\s+\('(pub-\d+)'\)")
    # Find all spec values following each QID
    const_pattern = re.compile(r"LOAD_CONST\s+\d+\s+\((.+?)\)")
    
    lines = content.strip().split('\n')
    
    specs = {}
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        qid_match = qid_pattern.search(line)
        if qid_match:
            qid = qid_match.group(1)
            # Next lines should be: 'spec', item, qty, coupon, dest, tuple key
            # Look ahead for the spec values
            vals = []
            j = i + 1
            while j < len(lines) and len(vals) < 6:
                next_line = lines[j].strip()
                cm = const_pattern.search(next_line)
                if cm:
                    vals.append(cm.group(1))
                j += 1
            
            if len(vals) >= 5:
                # vals[0] = 'spec', vals[1] = item, vals[2] = qty, vals[3] = coupon, vals[4] = dest
                item = vals[1].strip("'")
                qty = int(vals[2])
                coupon_raw = vals[3].strip("'")
                coupon = None if coupon_raw == 'None' else coupon_raw
                dest_raw = vals[4].strip("'")
                dest = None if dest_raw == 'None' else dest_raw
                
                specs[qid] = {
                    'item': item,
                    'qty': qty,
                    'coupon': coupon,
                    'dest': dest
                }
            i = j
        else:
            i += 1
    
    return specs

def spec_to_question(qid, spec):
    """Convert a spec dict to a natural Vietnamese question string."""
    item = spec['item']
    qty = spec['qty']
    coupon = spec.get('coupon')
    dest = spec.get('dest')
    
    # Map item names to display names
    item_display = {
        'iphone': 'iPhone',
        'ipad': 'iPad',
        'macbook': 'MacBook',
        'airpods': 'AirPods',
        'oppo': 'Oppo',
        'sony': 'Sony',
        'nokia': 'Nokia',
        'xiaomi': 'Xiaomi',
    }
    
    # Map dest to display names  
    dest_display = {
        'ha noi': 'Ha Noi',
        'hà nội': 'Hà Nội',
        'tp hcm': 'TP HCM',
        'da nang': 'Da Nang',
        'đà nẵng': 'Đà Nẵng',
        'hai phong': 'Hai Phong',
        'hải phòng': 'Hải Phòng',
        'can tho': 'Can Tho',
        'vung tau': 'Vung Tau',
        'đà lạt': 'Đà Lạt',
    }
    
    display_item = item_display.get(item, item.capitalize())
    
    parts = [f"Mua {qty} {display_item}"]
    
    if coupon:
        parts.append(f"dung ma {coupon}")
    
    if dest:
        display_dest = dest_display.get(dest, dest.title())
        parts.append(f"ship {display_dest}")
    
    parts.append("tong bao nhieu?")
    
    return " ".join(parts)

def main():
    specs = parse_answer_key(ANSWER_KEY_FILE)
    
    # Sort by QID number
    sorted_qids = sorted(specs.keys(), key=lambda x: int(x.split('-')[1]))
    
    print(f"Parsed {len(sorted_qids)} questions from answer key")
    
    questions = []
    for qid in sorted_qids:
        q_text = spec_to_question(qid, specs[qid])
        questions.append({
            "qid": qid,
            "question": q_text
        })
        print(f"  {qid}: {q_text}")
    
    output_path = "/Users/haiannguyen/Desktop/Day-13-Lab-Observathon/harness/public_questions_120.json"
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(questions, f, ensure_ascii=False, indent=2)
    
    print(f"\nSaved {len(questions)} questions to {output_path}")

if __name__ == '__main__':
    main()
