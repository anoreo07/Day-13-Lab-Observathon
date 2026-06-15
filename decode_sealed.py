import json
import base64

with open("run_output_private.json", "r") as f:
    data = json.load(f)
    
sealed_data = data.get("sealed", {}).get("data", "")
decoded_bytes = base64.b64decode(sealed_data)
decoded_str = decoded_bytes.decode('utf-8')
decoded_json = json.loads(decoded_str)

print(f"Decoded {len(decoded_json)} metric entries.")
# Print first 2 entries
print(json.dumps(decoded_json[:2], indent=2))
