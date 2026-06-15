import json
import sys
import os

# Thêm đường dẫn PYZ.pyz_extracted để có thể import module của simulator
extracted_path = "/Users/haiannguyen/Desktop/Day-13-Lab-Observathon/observathon-sim2_extracted/PYZ.pyz_extracted"
if extracted_path not in sys.path:
    sys.path.insert(0, extracted_path)

try:
    from observathon_sim import _dataset
    
    # Dataset là danh sách chứa các dict dạng:
    # { 'qid': 'prv-001', 'question': '...', 'spec': { 'item': 'macbook', ... }, ... }
    dataset_list = _dataset.DATASET
    print(f"Loaded dataset containing {len(dataset_list)} items.")
    
    # Tạo answer key cho private
    private_key = {}
    for item in dataset_list:
        qid = item['qid']
        spec = item['spec']
        private_key[qid] = {
            "spec": spec
        }
        
    output_path = "/Users/haiannguyen/Desktop/Day-13-Lab-Observathon/private_answerkey.json"
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(private_key, f, ensure_ascii=False, indent=2)
        
    print(f"Successfully generated private answerkey at: {output_path}")

except Exception as e:
    print(f"Error extracting private answerkey: {e}")
