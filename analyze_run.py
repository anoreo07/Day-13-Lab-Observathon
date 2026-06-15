import json
import re
import unicodedata

# Cấu trúc của catalog và ship
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

_SHIP_TABLE = {
    'ha noi': 30000,
    'hà nội': 30000,
    'tp hcm': 25000,
    'da nang': 35000,
    'đà nẵng': 35000,
    'hai phong': 28000,
    'hải phòng': 28000
}

def normalize_text(s):
    if not s:
        return ''
    s = s.strip().lower()
    s = s.replace('đ', 'd')
    # Normalize unicode to strip diacritics
    s = ''.join(
        c for c in unicodedata.normalize('NFKD', s)
        if unicodedata.category(c) != 'Mn'
    )
    return s.strip()

def calculate_expected(item, qty, coupon, dest):
    # Chuẩn hóa tên sản phẩm
    item_key = item.lower().strip()
    if item_key not in _CATALOG:
        return "refuse", "San pham khong co hang (item not found)"
    
    cat = _CATALOG[item_key]
    if not cat["in_stock"] or cat["quantity"] <= 0:
        return "refuse", "San pham khong co hang"
    
    # Check coupon
    discount_percent = 0
    if coupon:
        coupon_key = coupon.strip().upper()
        if coupon_key in _COUPONS:
            discount_percent = _COUPONS[coupon_key]
            
    # Check shipping destination
    if dest:
        dest_norm = normalize_text(dest)
        if dest_norm not in _SHIP_TABLE:
            return "refuse", "Khong giao hang den khu vuc nay"
        
        base_ship = _SHIP_TABLE[dest_norm]
        # Tính trọng lượng tổng cộng
        total_weight = cat["weight_kg"] * qty
        shipping_cost = base_ship + int(max(0.0, total_weight - 1.0) * 5000)
    else:
        return "refuse", "Khong giao hang den khu vuc nay (destination missing)"
        
    # Tính toán giá tiền
    subtotal = cat["unit_price_vnd"] * qty
    discounted = subtotal * (100 - discount_percent) // 100
    total = discounted + shipping_cost
    return "ok", total

def parse_actual_total(answer):
    if not answer:
        return None
    match = re.search(r'(?:tong\s*cong|tong\s*thanh\s*toan|tong\s*tien|tong|total)\s*[:\-]?\s*([\d\.,\s]+)\s*(?:vnd|đ|d)?', answer, re.IGNORECASE)
    if match:
        num_str = match.group(1).replace('.', '').replace(',', '').replace(' ', '')
        try:
            return int(num_str)
        except ValueError:
            pass
    return None

def analyze_mismatches(run_path, answerkey_path):
    with open(run_path, 'r', encoding='utf-8') as f:
        run_data = json.load(f)
    with open(answerkey_path, 'r', encoding='utf-8') as f:
        answerkey = json.load(f)
        
    results = run_data.get('results', [])
    mismatches = []
    
    for r in results:
        qid = r.get('qid')
        answer = r.get('answer', '')
        question = r.get('question', '')
        
        spec_data = answerkey.get(qid, {})
        spec = spec_data.get('spec', {})
        
        item = spec.get('item')
        qty = spec.get('qty', 1)
        coupon = spec.get('coupon')
        dest = spec.get('dest')
        
        expected_status, expected_val = calculate_expected(item, qty, coupon, dest)
        actual_total = parse_actual_total(answer)
        
        is_correct = True
        error_msg = ""
        
        if expected_status == "refuse":
            # Nếu câu hỏi gốc không có dest (tức là chỉ hỏi tồn kho, không có ý định ship)
            if dest is None or dest == '':
                # Đây là câu hỏi tồn kho, agent trả lời bình thường và không có tổng tiền
                if actual_total is not None:
                    is_correct = False
                    error_msg = f"Stock-only check: should not output total, but got {actual_total}"
                elif "khong" in answer.lower() and "ipad" in question.lower() and _CATALOG["ipad"]["in_stock"]:
                    is_correct = False
                    error_msg = f"Stock-only check: item is in stock but agent said out of stock"
            else:
                # Agent phải từ chối (refuse)
                if actual_total is not None:
                    is_correct = False
                    error_msg = f"Should refuse ({expected_val}) but generated total {actual_total}"
                elif "khong" not in answer.lower() and "tiec" not in answer.lower():
                    is_correct = False
                    error_msg = f"Should refuse ({expected_val}) but got answer: '{answer}'"
        else:
            if actual_total is None:
                is_correct = False
                error_msg = f"Expected total {expected_val} but couldn't parse actual total from answer: '{answer}'"
            elif actual_total != expected_val:
                is_correct = False
                error_msg = f"Arithmetic error: expected {expected_val}, got {actual_total}"
                
        if not is_correct:
            mismatches.append({
                'qid': qid,
                'question': question,
                'spec': spec,
                'expected_status': expected_status,
                'expected_val': expected_val,
                'actual_total': actual_total,
                'answer': answer,
                'error_msg': error_msg
            })
            
    print(f"Total mismatches: {len(mismatches)} / {len(results)}")
    for m in mismatches:
        print(f"[{m['qid']}] {m['question']}")
        print(f"  Error: {m['error_msg']}")
        print(f"  Spec: {m['spec']}")
        print(f"  Agent Answer: {m['answer'].strip()}")
        print("-" * 60)

analyze_mismatches("run_output_private_fixed.json", "private_answerkey.json")
