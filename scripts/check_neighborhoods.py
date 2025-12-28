# scripts/check_neighborhoods.py
import json

with open('yad2_next_data.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

# Get listings
items = data['props']['pageProps']['dehydratedState']['queries'][3]['state']['data']['private']

# Extract unique neighborhoods
neighborhoods = set()
for item in items:
    addr = item.get('address', {})
    hood = addr.get('neighborhood', {}).get('text', '')
    if hood:
        neighborhoods.add(hood)

print(f"Found {len(neighborhoods)} unique neighborhoods in sample:")
for n in sorted(neighborhoods):
    print(f"  - {n}")
