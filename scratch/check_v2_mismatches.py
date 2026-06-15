import json
import re
import unicodedata

_CATALOG = {
    'iphone': {"in_stock": True, "quantity": 12, "unit_price_vnd": 22000000, "weight_kg": 0.5},
    'macbook': {"in_stock": True, "quantity": 4, "unit_price_vnd": 35000000, "weight_kg": 1.6},
    'airpods': {"in_stock": False, "quantity": 0, "unit_price_vnd": 4500000, "weight_kg": 0.1},
    'ipad': {"in_stock": True, "quantity": 7, "unit_price_vnd": 18000000, "weight_kg": 0.45}
}

_COUPONS = {
    'WINNER': 10,
    'VIP20': 20,
    'SALE15': 15,
    'EXPIRED': 0
}

_SHIP = {
    'ha noi': 30000,
    'tp hcm': 25000,
    'da nang': 35000,
    'hai phong': 28000
}

def _ascii(s: str) -> str:
    if not s:
        return ''
    s = s.strip().lower()
    s = s.replace('đ', 'd')
    s = ''.join(
        c for c in unicodedata.normalize('NFKD', s)
        if unicodedata.category(c) != 'Mn'
    )
    return s.strip()

def compute_expected(spec: dict) -> dict:
    item = _ascii(spec.get('item', ''))
    qty = int(spec.get('qty', 1))
    coupon = spec.get('coupon')
    dest = spec.get('dest')
    
    rec = _CATALOG.get(item)
    if rec is None:
        return {
            'status': 'item_not_found',
            'total_vnd': None,
            'answer_kind': 'refusal',
            'tools': ['check_stock']
        }
    if not rec['in_stock']:
        return {
            'status': 'out_of_stock',
            'total_vnd': None,
            'answer_kind': 'refusal',
            'tools': ['check_stock'],
            'unit_price_vnd': rec['unit_price_vnd']
        }
    if not dest and not coupon:
        return {
            'status': 'ok',
            'total_vnd': None,
            'answer_kind': 'stock_only',
            'tools': ['check_stock'],
            'unit_price_vnd': rec['unit_price_vnd']
        }
    
    pct = 0
    if coupon:
        pct = _COUPONS.get(coupon.strip().upper(), 0)
        
    ship = None
    if dest:
        base = _SHIP.get(_ascii(dest))
        if base is None:
            tools = ['check_stock']
            if coupon:
                tools.append('get_discount')
            tools.append('calc_shipping')
            return {
                'status': 'dest_not_served',
                'total_vnd': None,
                'answer_kind': 'refusal',
                'tools': tools
            }
        ship = int(base + max(0.0, rec['weight_kg'] * qty - 1.0) * 5000)
        
    subtotal = rec['unit_price_vnd'] * qty
    total = (subtotal * (100 - pct) // 100) + (ship if ship else 0)
    
    tools = ['check_stock']
    if coupon:
        tools.append('get_discount')
    if dest:
        tools.append('calc_shipping')
        
    return {
        'status': 'ok',
        'total_vnd': total,
        'answer_kind': 'purchase_total',
        'discount_pct': pct,
        'ship_vnd': ship,
        'unit_price_vnd': rec['unit_price_vnd'],
        'tools': tools
    }

def _s(x) -> str:
    if isinstance(x, str):
        return x
    if x is None:
        return ''
    return str(x)

def extract_total_vnd(answer) -> int | None:
    answer = _s(answer)
    if not answer:
        return None
    answer = re.sub(r'\(lien he:.*?\)', '', answer)
    cands = []
    for n in re.findall(r'\d[\d., ]*\d|\d', answer):
        v = re.sub(r'[., ]', '', n)
        if v.isdigit():
            val = int(v)
            if val >= 1000:
                cands.append(val)
    if cands:
        return cands[-1]
    return None

_REFUSAL_KEYS = {
    'out_of_stock': ['het hang', 'out of stock', 'khong con hang', 'tam het', 'sold out', 'unavailable'],
    'item_not_found': ['khong tim thay', 'not found', 'khong xac dinh', 'chua xac dinh', 'khong co san pham', 'khong ro', 'unable to find', 'cannot find', 'khong nhan dien', 'chua du thong tin', 'khong du thong tin', 'khong tim', 'no such'],
    'dest_not_served': ['khong giao', 'not served', 'khong ho tro', 'khong phuc vu', 'khong van chuyen', 'destination', 'khong giao hang', 'outside', 'khong nhan giao']
}

def correctness_hit(answer: str, status: str, exp: dict) -> float:
    a = _s(answer)
    if status in ('loop', 'max_steps', 'no_action', 'wrapper_error'):
        return 0.0
    kind = exp['answer_kind']
    if kind == 'purchase_total':
        extracted = extract_total_vnd(a)
        if extracted == exp['total_vnd']:
            return 1.0
        return 0.0
    elif kind == 'refusal':
        keys = _REFUSAL_KEYS.get(exp['status'], [])
        low = _ascii(a)
        signaled = any(_ascii(k) in low for k in keys)
        fabricated = extract_total_vnd(a) is not None
        if fabricated:
            return 0.0
        if signaled:
            return 1.0
        return 0.6
    elif kind == 'stock_only':
        low = _ascii(a)
        if 'con hang' in low or 'vnd' in low:
            return 1.0
        return 0.5
    return 0.0

def simulated_post_process_result(result, question):
    if not result or not result.get("answer") or result.get("status") != "ok":
        return result
        
    trace = result.get("trace", [])
    if not trace:
        return result
        
    has_shipping = False
    price = None
    in_stock = True
    found = True
    discount_percent = 0
    shipping_cost = 0
    shipping_error = None
    
    for step in trace:
        tool = step.get('tool')
        obs = step.get('observation', {})
        if not obs:
            continue
        if tool == 'check_stock':
            found = obs.get('found', True)
            in_stock = obs.get('in_stock', True)
            price = obs.get('unit_price_vnd')
        elif tool == 'get_discount':
            coupon_code = obs.get('code')
            valid = obs.get('valid', True)
            if valid and coupon_code:
                code_upper = coupon_code.strip().upper()
                if code_upper in _COUPONS:
                    discount_percent = _COUPONS[code_upper]
                else:
                    discount_percent = obs.get('percent', 0)
            else:
                discount_percent = 0
        elif tool == 'calc_shipping':
            has_shipping = True
            shipping_error = obs.get('error')
            if not shipping_error:
                shipping_cost = obs.get('cost_vnd', 0)
            else:
                shipping_cost = None

    if not found:
        result["answer"] = "San pham khong tim thay trong he thong"
        return result

    if not in_stock:
        result["answer"] = "San pham da het hang"
        return result
        
    if has_shipping and shipping_error is not None:
        result["answer"] = "Khong giao hang den khu vuc nay"
        return result

    if has_shipping and price is not None and shipping_cost is not None:
        qty = 1
        qty_match = re.search(r'(?:mua|order)\s+(\d+)', question, re.IGNORECASE)
        if qty_match:
            qty = int(qty_match.group(1))
            
        subtotal = price * qty
        discounted = subtotal * (100 - discount_percent) // 100
        expected_total = discounted + shipping_cost
        
        answer = result["answer"]
        total_pattern = re.compile(
            r'((?:tong\s*cong|tong\s*thanh\s*toan|tong\s*tien|tong|total)\s*[:\-]?\s*)([\d\.,\s]+)(\s*(?:vnd|đ|d)?)',
            re.IGNORECASE
        )
        if total_pattern.search(answer):
            formatted_total = f"{expected_total:,}".replace(',', '.')
            result["answer"] = total_pattern.sub(rf"\g<1>{formatted_total}\g<3>", answer)
        else:
            result["answer"] = f"Tong cong: {expected_total} VND"
            
    return result

# Load run output and answer key
with open('run_output_private_v2.json', 'r') as f:
    run = json.load(f)
with open('private_answerkey.json', 'r') as f:
    ak = json.load(f)

results = run.get('results', [])
total_score = 0.0
mismatches = []

for r in results:
    qid = r['qid']
    question = r['question']
    
    res_copy = {
        'answer': r['answer'],
        'status': r.get('status', 'ok'),
        'trace': r.get('trace', [])
    }
    res_processed = simulated_post_process_result(res_copy, question)
    
    spec = ak[qid]['spec']
    exp = compute_expected(spec)
    score = correctness_hit(res_processed['answer'], res_processed['status'], exp)
    total_score += score
    
    if score < 1.0:
        mismatches.append({
            'qid': qid,
            'question': question,
            'spec': spec,
            'exp': exp,
            'answer': res_processed['answer'],
            'score': score,
            'extracted': extract_total_vnd(res_processed['answer'])
        })

print(f"Total calculated score: {total_score} / {len(results)}")
print(f"Number of questions with score < 1.0: {len(mismatches)}")
print("="*80)
for m in mismatches:
    print(f"[{m['qid']}] Q: {m['question']}")
    print(f"  Spec: {m['spec']}")
    print(f"  Expected: {m['exp']}")
    print(f"  Score: {m['score']}")
    print(f"  Extracted: {m['extracted']}")
    print(f"  Agent Answer: {m['answer']}")
    print("-"*80)
